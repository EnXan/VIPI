"""Persist selected-image runs and their reference-coverage report."""

import json
import re
import threading
import uuid
from pathlib import Path

from .engine_pool import EnginePool
from .evaluation import summarize
from .pipeline import extract
from .storage import RunStore, write_json
from .runtime import DEFAULT_BACKEND, threads_per_worker, validate_backend


class Batch:
    def __init__(
        self, root, catalog, identifiers, model, workers, *, backend=DEFAULT_BACKEND
    ):
        validate_backend(model, backend)
        if not identifiers or len(set(identifiers)) != len(identifiers):
            raise ValueError("Choose at least one distinct dataset image.")
        items = []
        for identifier in identifiers:
            record = catalog.get(identifier)
            catalog.path(identifier)
            items.append(
                {
                    "dataset_id": identifier,
                    "image": record["image"],
                    "category": record["category"],
                    "state": "queued",
                    "run_id": None,
                    "valid": None,
                }
            )
        self.id = uuid.uuid4().hex
        self.directory = Path(root) / "batches" / self.id
        self.directory.mkdir(parents=True)
        self.lock = threading.RLock()
        self.status = {
            "batch_id": self.id,
            "state": "queued",
            "model": model,
            "workers": workers,
            "backend": backend,
            "threads_per_worker": threads_per_worker(workers),
            "completed": 0,
            "total": len(items),
            "current_run_id": None,
            "items": items,
        }
        self.save()

    def save(self):
        self.status["summary"] = summarize(self.status["items"])
        write_json(self.directory / "report.json", self.status)

    def snapshot(self):
        with self.lock:
            return json.loads(json.dumps(self.status))

    @classmethod
    def restore(cls, root, identifier):
        if not re.fullmatch(r"[a-f0-9]{32}", identifier):
            raise ValueError("Invalid batch ID.")
        batch = cls.__new__(cls)
        batch.id = identifier
        batch.directory = Path(root) / "batches" / identifier
        batch.lock = threading.RLock()
        batch.status = json.loads(
            (batch.directory / "report.json").read_text(encoding="utf-8")
        )
        if batch.status["state"] not in {"completed", "failed"}:
            batch.status.update(
                state="failed", error="Server stopped before this selection completed."
            )
            for item in batch.status["items"]:
                if item["state"] == "running":
                    item.update(state="failed", error="Processing interrupted.")
        # Refresh derived summaries for older reports without rerunning OCR.
        batch.save()
        return batch

    def run(self, root, models, catalog, jobs, engine_factory=None):
        try:
            with self.lock:
                self.status["state"] = "running"
                self.save()
            with EnginePool(
                self.status["model"],
                models,
                self.status["workers"],
                self.status.get("backend", DEFAULT_BACKEND),
                engine_factory,
            ) as pool:
                self._run_images(root, models, catalog, jobs, pool)
            with self.lock:
                self.status["state"] = "completed"
                self.save()
        except Exception as error:
            with self.lock:
                self.status.update(state="failed", error=str(error))
                self.save()

    def _run_images(self, root, models, catalog, jobs, pool):
        for item in self.status["items"]:
            store = RunStore(
                root,
                self.status["model"],
                workers=self.status["workers"],
                backend=self.status.get("backend", DEFAULT_BACKEND),
            )
            jobs[store.id] = store
            with self.lock:
                item.update(state="running", run_id=store.id)
                self.status["current_run_id"] = store.id
                self.save()
            try:
                reference = catalog.reference(item["dataset_id"])
                result = extract(
                    catalog.path(item["dataset_id"]),
                    self.status["model"],
                    store=store,
                    models_dir=models,
                    workers=self.status["workers"],
                    engine_pool=pool,
                    reference=reference,
                    backend=self.status.get("backend", DEFAULT_BACKEND),
                )
                evaluation = result["evaluation"]
                with self.lock:
                    item.update(
                        state="completed",
                        valid=evaluation["valid"],
                        coverage=evaluation["detection"]["coverage"],
                        missing=evaluation["detection"]["missing"],
                        final_valid=evaluation["final"]["valid"],
                        best_step_id=evaluation["best_step_id"],
                        effects=evaluation["effects"],
                    )
            except Exception as error:
                if store.status["state"] != "failed":
                    store.transition(
                        "run_failed",
                        state="failed",
                        active_steps={},
                        error=str(error),
                    )
                with self.lock:
                    item.update(state="failed", error=str(error))
            with self.lock:
                self.status["completed"] += 1
                self.save()
            # Completed run events can be restored from disk on demand.
            jobs.pop(store.id, None)
