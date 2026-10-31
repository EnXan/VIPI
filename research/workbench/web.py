"""One local run with configurable workers and live Server-Sent Events."""

import re
import json
import tempfile
import threading
from concurrent.futures import CancelledError
from pathlib import Path

from flask import Flask, Response, jsonify, render_template, request, send_file
from werkzeug.exceptions import RequestEntityTooLarge

from vipi.config import OCR_MODEL_IDS
from .presentation import image_links, sse_events

from .model_registry import (
    DEFAULT_MODEL,
    model_options,
    validate_model,
    backend_for,
    SINGLE_PASS_MODELS,
)
from .batch import Batch
from research.ocr_eval.evaluation.catalog import Catalog
from research.detection_eval.evaluation.catalog import Catalog as DetectionCatalog
from research.ocr_eval.evaluation.runner import extract
from research.ocr_eval.evaluation.profiles import DEFAULT_PROFILE, validate_profile
from .datasets import DatasetBrowser
from vipi.storage.ocr import RunStore
from vipi.ocr.transforms import decode_image, views_for_size
from vipi.ocr.workers import DEFAULT_WORKERS, MAX_WORKERS, worker_count
from vipi.ocr.runtime import DEFAULT_BACKEND, backend_options, validate_backend
from vipi.cancellation import check_cancelled


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
    run_cancellations = {}
    active = threading.Lock()
    repository = Path(repository_root or Path.cwd()).resolve()
    catalogs = {}
    browsers = {}
    from research.workbench.detection import DetectionService, register_routes

    detection = DetectionService(root, detector_models_dir, detector_provider_factory)
    register_routes(app, detection)

    def get_catalog(dataset="ocr_evaluation"):
        types = {"ocr_evaluation": Catalog, "detection_evaluation": DetectionCatalog}
        if dataset not in types:
            raise ValueError("Choose OCR evaluation or detection evaluation.")
        if dataset not in catalogs:
            catalogs[dataset] = types[dataset](repository)
        return catalogs[dataset]

    def get_browser(dataset):
        if dataset not in browsers:
            browsers[dataset] = DatasetBrowser(get_catalog(dataset), dataset)
        return browsers[dataset]

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
            models=[
                item for item in model_options(models) if item["id"] in OCR_MODEL_IDS
            ],
            default="ppocr-v6-tiny",
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
                get_browser(request.args.get("dataset", "ocr_evaluation")).listing(
                    request.args.get("category", ""),
                    request.args.get("q", ""),
                    offset,
                    limit,
                )
            )
        except (ValueError, OSError) as error:
            return jsonify(error=str(error)), 400

    @app.get("/api/datasets/<identifier>/reference")
    def dataset_reference(identifier):
        try:
            catalog = get_catalog(request.args.get("dataset", "ocr_evaluation"))
            return jsonify(catalog.reference(identifier))
        except (ValueError, OSError) as error:
            return jsonify(error=str(error)), 404

    @app.get("/api/datasets/<identifier>/image")
    def dataset_image(identifier):
        try:
            return send_file(
                get_catalog(request.args.get("dataset", "ocr_evaluation")).path(
                    identifier
                ),
                conditional=True,
            )
        except (ValueError, OSError) as error:
            return jsonify(error=str(error)), 404

    thumbnail_slots = threading.Semaphore(2)

    @app.get("/api/datasets/<identifier>/thumbnail")
    def dataset_thumbnail(identifier):
        try:
            with thumbnail_slots:
                return send_file(
                    get_browser(
                        request.args.get("dataset", "ocr_evaluation")
                    ).thumbnail(identifier),
                    mimetype="image/jpeg",
                    max_age=3600,
                )
        except (ValueError, OSError) as error:
            return jsonify(error=str(error)), 404

    @app.post("/api/batches")
    def start_batch():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify(error="Provide a dataset image selection."), 400
        try:
            if "selections" in data:
                selections = data["selections"]
                if not isinstance(selections, list) or not all(
                    isinstance(selection, dict)
                    and isinstance(selection.get("dataset"), str)
                    and isinstance(selection.get("id"), str)
                    for selection in selections
                ):
                    raise ValueError("Provide dataset and image ID for each selection.")
                selected_datasets = {selection["dataset"] for selection in selections}
                if not selected_datasets or not selected_datasets <= {
                    "ocr_evaluation",
                    "detection_evaluation",
                }:
                    raise ValueError("Choose a supported dataset collection.")
                selected = {name: get_catalog(name) for name in selected_datasets}
                for name in selected_datasets:
                    if sum(
                        selection["dataset"] == name for selection in selections
                    ) > len(selected[name].items):
                        raise ValueError("Selection exceeds the dataset catalog.")
                dataset = (
                    next(iter(selected_datasets))
                    if len(selected_datasets) == 1
                    else "mixed"
                )
            else:
                dataset = data.get("dataset", "ocr_evaluation")
                dataset_ids = data.get("dataset_ids")
                if (
                    not isinstance(dataset, str)
                    or not isinstance(dataset_ids, list)
                    or not all(
                        isinstance(identifier, str) for identifier in dataset_ids
                    )
                ):
                    raise ValueError("Provide a list of dataset image IDs.")
                selected = get_catalog(dataset)
                selections = [
                    {"dataset": dataset, "id": identifier} for identifier in dataset_ids
                ]
                if len(dataset_ids) > len(selected.items):
                    raise ValueError("Selection exceeds the dataset catalog.")
            workers = worker_count(data.get("workers", DEFAULT_WORKERS))
            profile = validate_profile(data.get("ocr_profile", DEFAULT_PROFILE))
            selected_models = data.get("models", [data.get("model", DEFAULT_MODEL)])
            if (
                not isinstance(selected_models, list)
                or not selected_models
                or not all(isinstance(model, str) for model in selected_models)
            ):
                raise ValueError("Choose one or more OCR models.")
            if profile in {"baseline", "adaptive-jev"}:
                workers = 1
            backend = data.get("backend", DEFAULT_BACKEND)
            for model in selected_models:
                validate_model(model, models)
                validate_backend(model, backend_for(model, backend))
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
                selections,
                selected_models,
                workers,
                backend=backend,
                detection_options=detection_options,
                dataset=dataset,
                ocr_profile=profile,
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

    @app.get("/api/batches/<identifier>/input")
    def batch_input(identifier):
        try:
            batch = get_batch(identifier)
            return send_file(
                batch.directory / "input.png", mimetype="image/png", conditional=True
            )
        except (ValueError, OSError):
            return jsonify(error="Uploaded image not found."), 404

    @app.post("/api/batches/<identifier>/cancel")
    def cancel_batch(identifier):
        try:
            batch = get_batch(identifier)
            requested = batch.cancel()
            if requested and batch.status.get("current_run_id"):
                detection.cancel(batch.status["current_run_id"])
            return jsonify(batch.snapshot()), 202 if requested else 200
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
            selected_models = (
                json.loads(request.form["models"])
                if request.form.get("models")
                else [model]
            )
            if (
                not isinstance(selected_models, list)
                or not selected_models
                or not all(isinstance(value, str) for value in selected_models)
            ):
                raise ValueError("Choose one or more OCR models.")
            model = selected_models[0]
            workers = worker_count(request.form.get("workers", DEFAULT_WORKERS))
            profile = validate_profile(request.form.get("ocr_profile", DEFAULT_PROFILE))
            detection_options = None
            if request.form.get("detection"):
                from vipi.detection.pipeline import settings

                supplied = json.loads(request.form["detection"])
                if not isinstance(supplied, dict):
                    raise ValueError("Detection options must be a JSON object.")
                detection_options = settings(**supplied)
            if model in SINGLE_PASS_MODELS or profile in {"baseline", "adaptive-jev"}:
                workers = 1
            backend = request.form.get("backend", DEFAULT_BACKEND)
            for selected in selected_models:
                validate_model(selected, models)
                validate_backend(
                    selected,
                    backend
                    if len(selected_models) == 1
                    else backend_for(selected, backend),
                )
            if len(selected_models) == 1:
                backend = backend_for(model, backend)
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
            if profile == "transforms":
                views_for_size(*image.size)
            if len(selected_models) > 1:
                from .uploads import UploadCatalog

                catalog = UploadCatalog(temporary, upload.filename)
                batch = Batch(
                    root,
                    catalog,
                    ["upload"],
                    selected_models,
                    workers,
                    backend=backend,
                    detection_options=detection_options,
                    dataset="upload",
                    ocr_profile=profile,
                )
                catalog.source = batch.directory / "input.png"
                image.save(catalog.source, format="PNG")
                temporary.unlink(missing_ok=True)
                batches[batch.id] = batch

                def run_uploaded_comparison():
                    try:
                        batch.run(
                            root,
                            models,
                            catalog,
                            jobs,
                            engine_factory,
                            detection_service=detection,
                        )
                    finally:
                        active.release()

                threading.Thread(
                    target=run_uploaded_comparison,
                    daemon=True,
                    name=f"comparison-{batch.id}",
                ).start()
                return jsonify(batch_id=batch.id), 202
            store = RunStore(root, model, workers=workers, backend=backend)
            jobs[store.id] = store
            cancel_event = threading.Event()
            run_cancellations[store.id] = cancel_event
            check_store = (
                detection.prepare(
                    store.id, detection_options, cancel_event=cancel_event
                )
                if detection_options
                else None
            )

            def worker():
                try:
                    extract(
                        temporary,
                        model,
                        ocr_profile=profile,
                        models_dir=models,
                        store=store,
                        engine_factory=engine_factory,
                        workers=workers,
                        backend=backend,
                        cancel_event=cancel_event,
                    )
                    check_cancelled(cancel_event)
                    if check_store:
                        detection.enqueue(check_store, detection_options)
                except CancelledError:
                    if check_store and check_store.status["state"] == "queued":
                        check_store.emit("detection_cancelled", state="cancelled")
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
                    run_cancellations.pop(store.id, None)
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

    @app.post("/api/runs/<run_id>/cancel")
    def cancel_run(run_id):
        job = get_job(run_id)
        if job is None:
            return jsonify(error="Run not found."), 404
        # A batch owns its current OCR run and any following detector work.
        for batch in list(batches.values()):
            if batch.status.get("current_run_id") == run_id and batch.status[
                "state"
            ] not in {"completed", "failed", "cancelled"}:
                batch.cancel()
                detection.cancel(run_id)
                return jsonify(cancel_requested=True), 202
        requested = detection.cancel(run_id)
        event = run_cancellations.get(run_id)
        if event is not None:
            event.set()
            requested = True
            with job.condition:
                if job.status["state"] not in {
                    "completed",
                    "failed",
                    "cancelled",
                } and not job.status.get("cancel_requested"):
                    job.transition("cancellation_requested", cancel_requested=True)
        return jsonify(cancel_requested=requested), 202 if requested else 200

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
