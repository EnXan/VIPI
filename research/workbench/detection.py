"""Local web adapter over the shared scanner, with independent replayable SSE."""

from concurrent.futures import ThreadPoolExecutor
import importlib.util
import json
import re
import threading
from pathlib import Path

from flask import Response, jsonify, request, send_file

from .presentation import sse_events

from vipi.config import api_key
from vipi.detection.evidence import run_directory
from vipi.detection.pipeline import detect_saved_run as detect, settings
from vipi.detection.providers.prompt_guard import MODEL_DIR, model_manifest
from vipi.storage.detection import DetectionStore


class DetectionService:
    def __init__(self, root, model_dir=MODEL_DIR, provider_factory=None):
        self.root = Path(root)
        self.model_dir = Path(model_dir)
        self.provider_factory = provider_factory
        self.stores = {}
        self.lock = threading.RLock()
        # One scan at a time, each with four API workers and one local-model worker.
        self.executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="detector-scan"
        )

    def prepare(self, run_id, options):
        options = settings(**options)
        directory = run_directory(self.root, run_id)
        if not (directory / "status.json").is_file():
            raise ValueError("OCR run not found.")
        store = DetectionStore(directory)
        store.emit("detection_queued", options=options, evidence_scope="final_ocr")
        with self.lock:
            self.stores[run_id, store.id] = store
        return store

    def enqueue(self, store, options):
        def worker():
            try:
                return detect(
                    store.directory.parent.parent,
                    options=options,
                    model_dir=self.model_dir,
                    store=store,
                    provider_factory=self.provider_factory,
                )
            except Exception as error:
                if store.status["state"] != "failed":
                    store.emit("detection_failed", state="failed", error=str(error))

        return self.executor.submit(worker)

    def get(self, run_id, check_id):
        directory = run_directory(self.root, run_id)
        if not re.fullmatch(r"[a-f0-9]{32}", check_id):
            raise ValueError("Invalid detection ID.")
        with self.lock:
            key = run_id, check_id
            if key not in self.stores:
                self.stores[key] = DetectionStore.restore(
                    directory / "detection" / check_id
                )
            return self.stores[key]

    def listing(self, run_id):
        directory = run_directory(self.root, run_id)
        entries = []
        for path in sorted(
            (directory / "detection").glob("*/status.json"),
            key=lambda x: x.stat().st_mtime,
        ):
            store = self.get(run_id, path.parent.name)
            with store.condition:
                entries.append(
                    {
                        key: value
                        for key, value in store.status.items()
                        if key != "answer"
                    }
                )
        return entries


def register_routes(app, service):
    @app.get("/api/detectors")
    def availability():
        reason = None
        try:
            model_manifest(service.model_dir, verify=False)
            if not importlib.util.find_spec("transformers"):
                raise ValueError("Install detector-local dependencies.")
        except ValueError as error:
            reason = str(error)
        return jsonify(
            default="jev",
            providers=[
                {
                    "id": "jev",
                    "label": "Jev",
                    "available": bool(api_key("TYPESAFE_API_KEY", "JEV_API_KEY")),
                    "reason": "TYPESAFE_API_KEY required",
                },
                {
                    "id": "openai",
                    "label": "OpenAI Decisions",
                    "available": bool(api_key("OPENAI_API_KEY")),
                    "reason": "OPENAI_API_KEY required",
                },
                {
                    "id": "prompt-guard",
                    "label": "Prompt Guard 2 · local",
                    "available": reason is None,
                    "reason": reason,
                },
            ],
        )

    @app.get("/api/runs/<run_id>/detections")
    def listing(run_id):
        try:
            if not (run_directory(service.root, run_id) / "status.json").is_file():
                raise ValueError("OCR run not found.")
            return jsonify(checks=service.listing(run_id))
        except (ValueError, OSError):
            return jsonify(error="OCR run not found."), 404

    @app.post("/api/runs/<run_id>/detections")
    def start(run_id):
        try:
            directory = run_directory(service.root, run_id)
            status = json.loads((directory / "status.json").read_text())
            if status["state"] not in {"completed", "failed"}:
                return jsonify(
                    error="Wait for OCR to finish before checking saved evidence."
                ), 409
            data = request.get_json(silent=True)
            if not isinstance(data, dict):
                raise ValueError("Provide detector options as a JSON object.")
            options = settings(**data)
            store = service.prepare(run_id, options)
            service.enqueue(store, options)
            return jsonify(check_id=store.id, run_id=run_id), 202
        except (ValueError, OSError, TypeError) as error:
            return jsonify(error=str(error)), 400

    @app.get("/api/runs/<run_id>/detections/<check_id>", endpoint="detection_snapshot")
    def snapshot(run_id, check_id):
        try:
            return jsonify(service.get(run_id, check_id).snapshot())
        except (ValueError, OSError):
            return jsonify(error="Detection not found."), 404

    @app.get(
        "/api/runs/<run_id>/detections/<check_id>/events", endpoint="detection_events"
    )
    def events(run_id, check_id):
        try:
            store = service.get(run_id, check_id)
        except (ValueError, OSError):
            return jsonify(error="Detection not found."), 404
        try:
            after = int(
                request.headers.get("Last-Event-ID", request.args.get("after", 0))
            )
            if not 0 <= after <= len(store.events):
                raise ValueError()
        except ValueError:
            return jsonify(error="Invalid detection event cursor."), 400
        return Response(
            sse_events(store, after),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get(
        "/api/runs/<run_id>/detections/<check_id>/result.json",
        endpoint="detection_download",
    )
    def download(run_id, check_id):
        try:
            store = service.get(run_id, check_id)
            path = store.directory / "result.json"
            if not path.is_file():
                return jsonify(error="Detection has no final report yet."), 409
            return send_file(
                path,
                as_attachment=True,
                download_name=f"vipi-detection-{check_id}.json",
            )
        except (ValueError, OSError):
            return jsonify(error="Detection not found."), 404

    @app.get("/api/runs/<run_id>/detections/<check_id>/readings")
    def readings(run_id, check_id):
        try:
            store = service.get(run_id, check_id)
            path = store.directory / "inputs.json"
            if not path.is_file():
                return jsonify(readings=[])
            return jsonify(
                readings=json.loads(path.read_text())["evidence"]["readings"]
            )
        except (ValueError, OSError):
            return jsonify(error="Detection not found."), 404
