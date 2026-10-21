"""One local run with configurable workers and live Server-Sent Events."""

import re
import json
import tempfile
import threading
from pathlib import Path

from flask import Flask, Response, jsonify, render_template, request, send_file
from werkzeug.exceptions import RequestEntityTooLarge

from .presentation import image_links, sse_events

from vipi.ocr.models import DEFAULT_MODEL, model_options, validate_model
from .batch import Batch
from research.datasets.catalog import Catalog
from .datasets import DatasetBrowser
from vipi.ocr.pipeline import extract
from vipi.storage.ocr import RunStore
from vipi.ocr.transforms import decode_image, views_for_size
from vipi.ocr.workers import DEFAULT_WORKERS, MAX_WORKERS, worker_count
from vipi.ocr.runtime import DEFAULT_BACKEND, backend_options, validate_backend


def create_app(
    runs_dir="runs",
    models_dir="models/ocr",
    *,
    engine_factory=None,
    repository_root=None,
    detector_models_dir="models/detector/prompt-guard-2-86m",
    detector_provider_factory=None,
):
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 128 * 1024 * 1024
    root, models = Path(runs_dir).resolve(), Path(models_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    jobs = {}
    batches = {}
    active = threading.Lock()
    repository = Path(repository_root or Path.cwd()).resolve()
    catalog = None
    browser = None
    from research.workbench.detection import DetectionService, register_routes

    detection = DetectionService(root, detector_models_dir, detector_provider_factory)
    register_routes(app, detection)

    def get_catalog():
        nonlocal catalog
        if catalog is None:
            catalog = Catalog(repository)
        return catalog

    def get_browser():
        nonlocal browser
        if browser is None:
            browser = DatasetBrowser(get_catalog())
        return browser

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
            return jsonify(error="Cross-origin uploads are not accepted."), 403

    @app.errorhandler(RequestEntityTooLarge)
    def too_large(error):
        return jsonify(error="Upload exceeds 128 MiB."), 413

    @app.get("/")
    def index():
        return render_template(
            "index.html", default_workers=DEFAULT_WORKERS, max_workers=MAX_WORKERS
        )

    @app.get("/api/models")
    def available_models():
        return jsonify(
            models=model_options(models),
            default=DEFAULT_MODEL,
            backends=backend_options(),
            default_backend=DEFAULT_BACKEND,
        )

    @app.get("/api/datasets")
    def dataset_images():
        try:
            offset, limit = (
                int(request.args.get("offset", 0)),
                int(request.args.get("limit", 12)),
            )
            if offset < 0 or not 1 <= limit <= 48:
                raise ValueError("Invalid dataset page.")
            return jsonify(
                get_browser().listing(
                    request.args.get("category", ""),
                    request.args.get("q", ""),
                    offset,
                    limit,
                )
            )
        except (ValueError, OSError) as error:
            return jsonify(error=str(error)), 400

    @app.get("/api/datasets/<identifier>/image")
    def dataset_image(identifier):
        try:
            return send_file(get_catalog().path(identifier), conditional=True)
        except (ValueError, OSError) as error:
            return jsonify(error=str(error)), 404

    thumbnail_slots = threading.Semaphore(2)

    @app.get("/api/datasets/<identifier>/thumbnail")
    def dataset_thumbnail(identifier):
        try:
            with thumbnail_slots:
                return send_file(
                    get_browser().thumbnail(identifier),
                    mimetype="image/jpeg",
                    max_age=3600,
                )
        except (ValueError, OSError) as error:
            return jsonify(error=str(error)), 404

    @app.post("/api/batches")
    def start_batch():
        data = request.get_json(silent=True)
        if (
            not isinstance(data, dict)
            or not isinstance(data.get("dataset_ids"), list)
            or not all(
                isinstance(identifier, str) for identifier in data["dataset_ids"]
            )
        ):
            return jsonify(error="Provide a list of dataset image IDs."), 400
        try:
            selected = get_catalog()
            if len(data["dataset_ids"]) > len(selected.items):
                raise ValueError("Selection exceeds the dataset catalog.")
            workers = worker_count(data.get("workers", DEFAULT_WORKERS))
            model = data.get("model", DEFAULT_MODEL)
            if not isinstance(model, str):
                raise ValueError("Choose an OCR model.")
            validate_model(model, models)
            backend = data.get("backend", DEFAULT_BACKEND)
            validate_backend(model, backend)
            detection_options = None
            if data.get("detection") is not None:
                from vipi.detection.pipeline import settings

                if not isinstance(data["detection"], dict):
                    raise ValueError("Detection options must be a JSON object.")
                detection_options = settings(**data["detection"])
        except (ValueError, OSError, TypeError) as error:
            return jsonify(error=str(error)), 400
        if not active.acquire(blocking=False):
            return jsonify(
                error="A pipeline is already running. Wait for it to finish."
            ), 409
        try:
            batch = Batch(
                root,
                selected,
                data["dataset_ids"],
                model,
                workers,
                backend=backend,
                detection_options=detection_options,
            )
            batches[batch.id] = batch

            def run_batch():
                try:
                    batch.run(
                        root,
                        models,
                        selected,
                        jobs,
                        engine_factory,
                        detection_service=detection,
                    )
                finally:
                    active.release()

            threading.Thread(
                target=run_batch, daemon=True, name=f"batch-{batch.id}"
            ).start()
            return jsonify(batch_id=batch.id), 202
        except (ValueError, OSError) as error:
            active.release()
            return jsonify(error=str(error)), 400

    def get_batch(identifier):
        if identifier not in batches:
            batches[identifier] = Batch.restore(root, identifier)
        return batches[identifier]

    @app.get("/api/batches/<identifier>")
    def batch_status(identifier):
        try:
            return jsonify(get_batch(identifier).snapshot())
        except (ValueError, OSError):
            return jsonify(error="Selection run not found."), 404

    @app.get("/api/batches/<identifier>/report.json")
    def batch_report(identifier):
        try:
            batch = get_batch(identifier)
            return send_file(
                batch.directory / "report.json",
                as_attachment=True,
                download_name=f"vipi-selection-{identifier}.json",
            )
        except (ValueError, OSError):
            return jsonify(error="Selection run not found."), 404

    def get_job(run_id):
        if not re.fullmatch(r"[a-f0-9]{32}", run_id):
            return None
        if run_id not in jobs and (root / run_id / "status.json").is_file():
            jobs[run_id] = RunStore.restore(root / run_id)
        return jobs.get(run_id)

    @app.post("/api/runs")
    def start_run():
        upload = request.files.get("image")
        if upload is None or not upload.filename:
            return jsonify(error="Choose or paste an image."), 400
        model = request.form.get("model", DEFAULT_MODEL)
        try:
            workers = worker_count(request.form.get("workers", DEFAULT_WORKERS))
            detection_options = None
            if request.form.get("detection"):
                from vipi.detection.pipeline import settings

                supplied = json.loads(request.form["detection"])
                if not isinstance(supplied, dict):
                    raise ValueError("Detection options must be a JSON object.")
                detection_options = settings(**supplied)
            validate_model(model, models)
            backend = request.form.get("backend", DEFAULT_BACKEND)
            validate_backend(model, backend)
        except (ValueError, TypeError) as error:
            return jsonify(error=str(error)), 400
        if not active.acquire(blocking=False):
            return jsonify(
                error="A pipeline is already running. Wait for it to finish."
            ), 409
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=root, suffix=".upload", delete=False
            ) as file:
                temporary = Path(file.name)
                upload.save(file)
            image = decode_image(temporary)
            views_for_size(*image.size)
            store = RunStore(root, model, workers=workers, backend=backend)
            jobs[store.id] = store
            check_store = (
                detection.prepare(store.id, detection_options)
                if detection_options
                else None
            )

            def worker():
                try:
                    extract(
                        temporary,
                        model,
                        models_dir=models,
                        store=store,
                        engine_factory=engine_factory,
                        workers=workers,
                        backend=backend,
                    )
                    if check_store:
                        detection.enqueue(check_store, detection_options)
                except Exception as error:
                    if check_store:
                        check_store.emit(
                            "detection_failed",
                            state="failed",
                            error="OCR failed; start detection on the saved partial run explicitly.",
                        )
                    if store.status["state"] != "failed":
                        store.transition(
                            "run_failed",
                            state="failed",
                            active_steps={},
                            error=str(error),
                            completed=store.status["completed"],
                        )
                finally:
                    temporary.unlink(missing_ok=True)
                    active.release()

            threading.Thread(target=worker, daemon=True, name=f"ocr-{store.id}").start()
            return jsonify(run_id=store.id), 202
        except Exception as error:
            if temporary:
                temporary.unlink(missing_ok=True)
            active.release()
            return jsonify(error=str(error)), 400

    @app.get("/api/runs/<run_id>")
    def snapshot(run_id):
        job = get_job(run_id)
        return (
            jsonify(image_links(job.snapshot(), run_id))
            if job
            else (jsonify(error="Run not found."), 404)
        )

    @app.get("/api/runs/<run_id>/events")
    def events(run_id):
        job = get_job(run_id)
        if job is None:
            return jsonify(error="Run not found."), 404
        try:
            after = int(
                request.headers.get("Last-Event-ID", request.args.get("after", 0))
            )
            if after < 0 or after > len(job.events):
                raise ValueError()
        except ValueError:
            return jsonify(error="Invalid event cursor."), 400
        return Response(
            sse_events(job, after),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/api/runs/<run_id>/input")
    def original_image(run_id):
        job = get_job(run_id)
        if job is None:
            return jsonify(error="Image not found."), 404
        path = job.directory / "input.png"
        # Older runs saved only transformed images; the unchanged original is equivalent.
        if not path.is_file():
            original = next(
                (
                    step
                    for step in job.snapshot()["variants"]
                    if step.get("view_id") == "original"
                    and step.get("filter") == "unchanged"
                ),
                None,
            )
            if original:
                path = job.directory / "images" / f"{original['id']}.png"
        if not path.is_file():
            return jsonify(error="Image not found."), 404
        return send_file(path, mimetype="image/png", conditional=True)

    @app.get("/api/runs/<run_id>/steps/<step_id>/image")
    def step_image(run_id, step_id):
        job = get_job(run_id)
        if job is None or not re.fullmatch(r"\d{4,6}", step_id):
            return jsonify(error="Image not found."), 404
        path = job.directory / "images" / f"{step_id}.png"
        if not path.is_file():
            return jsonify(error="Image not found."), 404
        return send_file(path, mimetype="image/png", conditional=True)

    @app.get("/api/runs/<run_id>/result.<extension>")
    def download(run_id, extension):
        job = get_job(run_id)
        if job is None or extension not in {"txt", "json"}:
            return jsonify(error="Result not found."), 404
        if job.status["state"] != "completed":
            return jsonify(error="The pipeline has no final result yet."), 409
        return send_file(
            job.directory / f"result.{extension}",
            as_attachment=True,
            download_name=f"vipi-{run_id}.{extension}",
        )

    return app
