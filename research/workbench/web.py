"""The local workbench: scan an image, evaluate a configuration, contribute to the dataset."""

from pathlib import Path
import threading

from flask import Flask, jsonify, render_template, request, send_file
from werkzeug.exceptions import RequestEntityTooLarge

from vipi.config import DEFAULT_THRESHOLD, ScanOptions

from research.evaluate.suite import CONFIGURATIONS, SPLIT_NAMES
from research.ocr_eval import benchmark

from .evaluations import EvaluationService
from .scans import DEFAULT_CONFIGURATION, ScanService

OCR_LABELS = {
    "speed": "Speed",
    "balanced": "Balanced",
    "quality": "Quality",
    "google": "Google Cloud Vision",
    "openai": "OpenAI",
    "mistral": "Mistral",
}
DETECTOR_LABELS = {
    "d1": "d1 (LiquidAI d1-3B)",
    "clef": "Clef (Cloudflare)",
    "openai": "OpenAI Luna",
    "jev": "Jev",
}


def configuration_options():
    options = []
    for name, values in CONFIGURATIONS.items():
        local = values["ocr_execution_mode"] == "local"
        ocr = values.get("ocr_mode") or values.get("ocr_provider")
        detector = ScanOptions(**values).resolved_detector
        options.append(
            {
                "id": name,
                "run_on": "local" if local else "cloud",
                "ocr": ocr,
                "ocr_label": OCR_LABELS[ocr],
                "detector": detector,
                "detector_label": DETECTOR_LABELS[detector],
                "label": f"{'Local' if local else 'Cloud'} · {OCR_LABELS[ocr]}"
                + (" OCR" if local else "")
                + f" · {DETECTOR_LABELS[detector]} detector",
                "paid": not local,
            }
        )
    return options


def create_app(
    *,
    repository_root=None,
    curation_dir=None,
    scanner=None,
    evaluation_runner=None,
):
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 128 * 1024 * 1024
    repository = Path(repository_root or benchmark.ROOT).resolve()
    busy = threading.Lock()
    scans = ScanService(busy, scanner)
    evaluations = (
        EvaluationService(busy, repository, evaluation_runner)
        if evaluation_runner
        else EvaluationService(busy, repository)
    )

    from research.curation.store import DEFAULT_DIRECTORY, CurationStore
    from .curation_routes import register_routes as register_curation_routes

    register_curation_routes(
        app,
        CurationStore(
            Path(curation_dir) if curation_dir else repository / DEFAULT_DIRECTORY
        ),
    )

    @app.before_request
    def local_requests():
        if request.host.split(":")[0] not in {"127.0.0.1", "localhost"}:
            return jsonify(error="Use the local server address."), 400
        origin = request.headers.get("Origin")
        if (
            request.method == "POST"
            and origin
            and origin.rstrip("/") != request.host_url.rstrip("/")
        ):
            return jsonify(error="Cross-origin requests are not accepted."), 403

    @app.errorhandler(RequestEntityTooLarge)
    def too_large(error):
        return jsonify(error="Upload exceeds 128 MiB."), 413

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/api/configurations")
    def configurations():
        return jsonify(
            configurations=configuration_options(),
            default=DEFAULT_CONFIGURATION,
            threshold=DEFAULT_THRESHOLD,
            splits=list(SPLIT_NAMES),
        )

    # Scan an image

    @app.post("/api/scans")
    def start_scan():
        upload = request.files.get("image")
        if upload is None or not upload.filename:
            return jsonify(error="Choose, drop or paste an image."), 400
        try:
            threshold = float(request.form.get("threshold", DEFAULT_THRESHOLD))
            job = scans.start(
                upload.read(),
                request.form.get("configuration", DEFAULT_CONFIGURATION),
                threshold,
            )
        except ValueError as error:
            return jsonify(error=str(error)), 400
        except RuntimeError as error:
            return jsonify(error=str(error)), 409
        return jsonify(id=job.id), 202

    @app.get("/api/scans/<identifier>")
    def scan_status(identifier):
        try:
            return jsonify(scans.get(identifier).snapshot())
        except KeyError:
            return jsonify(error="Scan not found."), 404

    @app.get("/api/scans/<identifier>/steps/<step_id>.png")
    def scan_step_image(identifier, step_id):
        try:
            path = scans.get(identifier).step_image(step_id)
        except (KeyError, ValueError):
            return jsonify(error="Image not found."), 404
        return send_file(path, mimetype="image/png")

    # Evaluate a configuration

    def evaluation_error(error):
        if isinstance(error, KeyError):
            return jsonify(error="Evaluation run not found."), 404
        if isinstance(error, RuntimeError):
            return jsonify(error=str(error)), 409
        return jsonify(error=str(error)), 400

    @app.get("/api/evaluations")
    def evaluation_runs():
        return jsonify(runs=evaluations.listing())

    @app.get("/api/evaluations/setup")
    def evaluation_setup():
        configuration = request.args.get("configuration", DEFAULT_CONFIGURATION)
        split = request.args.get("split", "development")
        try:
            planned = evaluations.plan(configuration, split, confirm_test=True)
            baseline = evaluations.baseline(configuration, split)
        except (ValueError, OSError) as error:
            return evaluation_error(error)
        return jsonify(
            entries=planned["entries"],
            reusable_ocr=planned.get("reusable_ocr", 0),
            reusable_complete=planned.get("reusable_complete", 0),
            baseline=baseline,
        )

    @app.post("/api/evaluations")
    def start_evaluation():
        data = request.get_json(silent=True) or {}
        try:
            run_id = evaluations.start(
                data.get("configuration", DEFAULT_CONFIGURATION),
                data.get("split", "development"),
                data.get("confirm_test") is True,
                reuse_ocr=data.get("reuse_ocr", True) is not False,
            )
        except (ValueError, RuntimeError, OSError) as error:
            return evaluation_error(error)
        return jsonify(run_id=run_id), 202

    @app.get("/api/evaluations/<run_id>")
    def evaluation_status(run_id):
        try:
            return jsonify(evaluations.describe(run_id))
        except (KeyError, ValueError) as error:
            return evaluation_error(KeyError(str(error)))

    @app.post("/api/evaluations/<run_id>/resume")
    def resume_evaluation(run_id):
        try:
            evaluations.start(None, None, False, run_id=run_id)
        except (ValueError, RuntimeError, OSError) as error:
            return evaluation_error(error)
        return jsonify(run_id=run_id), 202

    @app.post("/api/evaluations/<run_id>/stop")
    def stop_evaluation(run_id):
        return jsonify(stopping=evaluations.stop(run_id))

    @app.post("/api/evaluations/<run_id>/baseline")
    def save_baseline(run_id):
        try:
            target = evaluations.save_baseline(run_id)
        except ValueError as error:
            return evaluation_error(error)
        return jsonify(path=target.relative_to(repository).as_posix())

    @app.get("/api/evaluations/<run_id>/<name>")
    def evaluation_markdown(run_id, name):
        try:
            path = evaluations.markdown(run_id, name)
        except (KeyError, ValueError) as error:
            return evaluation_error(KeyError(str(error)))
        return send_file(
            path,
            mimetype="text/markdown",
            as_attachment=True,
            download_name=f"{run_id}-{name}",
        )

    return app
