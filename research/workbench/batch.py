"""Persist selected-image runs and their reference-coverage report."""

import json
import re
import threading
import uuid
from concurrent.futures import CancelledError
from pathlib import Path

from vipi.ocr.engine_pool import EnginePool
from research.ocr_eval.evaluation.metrics import summarize
from research.ocr_eval.evaluation.runner import extract
from research.detection_eval.evaluation.metrics import summarize as detection_summary
from research.detection_eval.evaluation.runner import run_cases
from vipi.storage.ocr import RunStore, write_json
from vipi.ocr.runtime import DEFAULT_BACKEND, threads_per_worker, validate_backend
from vipi.cancellation import check_cancelled


class Batch:
    def __init__(
        self,
        root,
        catalog,
        identifiers,
        model,
        workers,
        *,
        backend=DEFAULT_BACKEND,
        detection_options=None,
        dataset="ocr_evaluation",
    ):
        validate_backend(model, backend)
        if dataset == "detection_evaluation" and not detection_options:
            raise ValueError("Select at least one detector for detection evaluation.")
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
                    "reference_text": catalog.reference(identifier)["text"],
                    "recognized_text": None,
                    "state": "queued",
                    "run_id": None,
                    "valid": None,
                }
            )
            if dataset == "detection_evaluation":
                items[-1].update(
                    techniques=record["techniques"],
                    obfuscation=record["obfuscation"],
                    cases=[
                        {**case, "case_index": index, "state": "queued"}
                        for index, case in enumerate(record["cases"], 1)
                    ],
                )
        self.id = uuid.uuid4().hex
        self.directory = Path(root) / "batches" / self.id
        self.directory.mkdir(parents=True)
        self.lock = threading.RLock()
        self.cancel_event = threading.Event()
        self.status = {
            "batch_id": self.id,
            "dataset": dataset,
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
        if detection_options:
            if dataset == "detection_evaluation":
                detection_options = {**detection_options, "context": {}}
                self.status["detection_context_mode"] = "none"
            self.status["detection_options"] = detection_options
        self.save()

    def save(self):
        self.status["summary"] = summarize(self.status["items"])
        if self.status.get("dataset") == "detection_evaluation":
            self.status["detection_evaluation"] = detection_summary(
                self.status["items"], self.status["detection_options"]
            )
        write_json(self.directory / "report.json", self.status)

    def snapshot(self):
        with self.lock:
            return json.loads(json.dumps(self.status))

    def cancel(self):
        with self.lock:
            if self.status["state"] in {"completed", "failed", "cancelled"}:
                return False
            self.cancel_event.set()
            self.status["cancel_requested"] = True
            self.save()
            return True

    @classmethod
    def restore(cls, root, identifier):
        if not re.fullmatch(r"[a-f0-9]{32}", identifier):
            raise ValueError("Invalid batch ID.")
        batch = cls.__new__(cls)
        batch.id = identifier
        batch.directory = Path(root) / "batches" / identifier
        batch.lock = threading.RLock()
        batch.cancel_event = threading.Event()
        batch.status = json.loads(
            (batch.directory / "report.json").read_text(encoding="utf-8")
        )
        if batch.status["state"] not in {"completed", "failed", "cancelled"}:
            batch.status.update(
                state="failed", error="Server stopped before this selection completed."
            )
            for item in batch.status["items"]:
                if item["state"] == "running":
                    item.update(state="failed", error="Processing interrupted.")
                for case in item.get("cases", []):
                    if item["state"] == "failed" and case["state"] in {
                        "queued",
                        "running",
                    }:
                        case.update(
                            state="failed",
                            outcome="error",
                            error="Processing interrupted.",
                        )
        # Refresh derived summaries for older reports without rerunning OCR.
        batch.save()
        return batch

    def run(
        self,
        root,
        models,
        catalog,
        jobs,
        engine_factory=None,
        *,
        detection_service=None,
    ):
        try:
            check_cancelled(self.cancel_event)
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
                self._run_images(root, models, catalog, jobs, pool, detection_service)
            with self.lock:
                check_cancelled(self.cancel_event)
                self.status["state"] = "completed"
                self.save()
        except CancelledError:
            with self.lock:
                self.status["state"] = "cancelled"
                for item in self.status["items"]:
                    if item["state"] in {"queued", "running"}:
                        item["state"] = "cancelled"
                    for case in item.get("cases", []):
                        if case["state"] in {"queued", "running"}:
                            case.update(state="cancelled", outcome="cancelled")
                self.save()
        except Exception as error:
            with self.lock:
                self.status.update(state="failed", error=str(error))
                self.save()

    def _run_images(self, root, models, catalog, jobs, pool, detection_service=None):
        for item in self.status["items"]:
            check_cancelled(self.cancel_event)
            store = RunStore(
                root,
                self.status["model"],
                workers=self.status["workers"],
                backend=self.status.get("backend", DEFAULT_BACKEND),
            )
            jobs[store.id] = store
            options = self.status.get("detection_options")
            check_store = (
                detection_service.prepare(
                    store.id, options, cancel_event=self.cancel_event
                )
                if options and detection_service and "cases" not in item
                else None
            )
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
                    cancel_event=self.cancel_event,
                )
                evaluation = result["evaluation"]
                detection_result = (
                    detection_service.enqueue(check_store, options).result()
                    if check_store
                    else None
                )
                with self.lock:
                    item.update(
                        state="running",
                        recognized_text=result.get("text", ""),
                        valid=evaluation["valid"],
                        coverage=evaluation["detection"]["coverage"],
                        missing=evaluation["detection"]["missing"],
                        final_valid=evaluation["final"]["valid"],
                        best_step_id=evaluation["best_step_id"],
                        effects=evaluation["effects"],
                    )
                    if check_store:
                        item["detection"] = {
                            "check_id": check_store.id,
                            "verdict": detection_result["verdict"]
                            if detection_result
                            else "unclear",
                            "state": check_store.status["state"],
                            "signals": detection_result.get("signals", {})
                            if detection_result
                            else {},
                            "threshold_version": detection_result.get(
                                "threshold_version"
                            )
                            if detection_result
                            else None,
                        }
                if "cases" in item:
                    with self.lock:
                        for case in item["cases"]:
                            case["state"] = "running"
                        self.save()
                    checked = run_cases(
                        store.id,
                        item["cases"],
                        options,
                        detection_service,
                        cancel_event=self.cancel_event,
                    )
                    with self.lock:
                        for case, result in zip(item["cases"], checked, strict=True):
                            case.update(result)
                        self.save()
                with self.lock:
                    check_cancelled(self.cancel_event)
                    item["state"] = "completed"
            except CancelledError:
                if check_store and check_store.status["state"] == "queued":
                    check_store.emit("detection_cancelled", state="cancelled")
                jobs.pop(store.id, None)
                raise
            except Exception as error:
                if check_store and check_store.status["state"] == "queued":
                    check_store.emit(
                        "detection_failed",
                        state="failed",
                        error="OCR failed; inspect the partial run explicitly.",
                    )
                if store.status["state"] != "failed":
                    store.transition(
                        "run_failed",
                        state="failed",
                        active_steps={},
                        error=str(error),
                    )
                with self.lock:
                    item.update(state="failed", error=str(error))
                    for case in item.get("cases", []):
                        if case["state"] not in {"completed", "failed"}:
                            case.update(
                                state="failed", outcome="error", error=str(error)
                            )
            with self.lock:
                self.status["completed"] += 1
                self.save()
            # Completed run events can be restored from disk on demand.
            jobs.pop(store.id, None)
