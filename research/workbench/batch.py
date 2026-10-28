"""Persist selected-image runs and their reference-coverage report."""

import json
import hashlib
import re
import threading
import uuid
import copy
import time
from concurrent.futures import CancelledError
from pathlib import Path

from vipi.ocr.engine_pool import EnginePool
from research.ocr_eval.evaluation.metrics import (
    EVALUATION_VERSION,
    evaluation_policy,
    summarize,
)
from research.ocr_eval.evaluation.runner import extract
from research.ocr_eval.evaluation.profiles import (
    DEFAULT_PROFILE,
    engine_factory_for,
    validate_profile,
)
from research.detection_eval.evaluation.metrics import summarize as detection_summary
from research.detection_eval.evaluation.runner import run_cases
from vipi.storage.ocr import RunStore, write_json
from vipi.storage.files import sha256
from vipi.ocr.runtime import DEFAULT_BACKEND, threads_per_worker, validate_backend
from vipi.cancellation import check_cancelled
from .model_registry import backend_for, SINGLE_PASS_MODELS
from .model_runtime import ModelInitializationError
from .ocr_costs import cost_for_result, performance_summary


def reference_digest(reference):
    if reference is None:
        return None
    return hashlib.sha256(
        json.dumps(reference, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


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
        ocr_profile=DEFAULT_PROFILE,
    ):
        validate_profile(ocr_profile)
        selected_models = [model] if isinstance(model, str) else list(model)
        if not selected_models or len(set(selected_models)) != len(selected_models):
            raise ValueError("Choose each OCR model once.")
        for selected_model in selected_models:
            validate_backend(selected_model, backend_for(selected_model, backend))
        if ocr_profile == "baseline":
            workers = 1
        catalogs = catalog if isinstance(catalog, dict) else {dataset: catalog}
        selections = [
            selection
            if isinstance(selection, dict)
            else {"dataset": dataset, "id": selection}
            for selection in identifiers
        ]
        selection_keys = [(item["dataset"], item["id"]) for item in selections]
        if not selections or len(set(selection_keys)) != len(selections):
            raise ValueError("Choose at least one distinct dataset image.")
        items = []
        for selection in selections:
            item_dataset, identifier = selection["dataset"], selection["id"]
            item_catalog = catalogs.get(item_dataset)
            if item_catalog is None:
                raise ValueError("Choose a supported dataset collection.")
            record = item_catalog.get(identifier)
            image_path = item_catalog.path(identifier)
            reference = item_catalog.reference(identifier)
            items.append(
                {
                    "dataset": item_dataset,
                    "dataset_id": identifier,
                    "image": record["image"],
                    "category": record["category"],
                    "reference_text": reference["text"] if reference else None,
                    "reference_available": reference is not None,
                    "input_sha256": sha256(image_path),
                    "reference_sha256": reference_digest(reference),
                    "recognized_text": None,
                    "state": "queued",
                    "run_id": None,
                    "valid": None,
                    "evaluation_version": EVALUATION_VERSION,
                }
            )
            if item_dataset == "detection_evaluation" and detection_options:
                items[-1].update(
                    techniques=record["techniques"],
                    obfuscation=record["obfuscation"],
                    cases=[
                        {**case, "case_index": index, "state": "queued"}
                        for index, case in enumerate(record["cases"], 1)
                    ],
                )
        items = [
            {**copy.deepcopy(item), "model": selected_model}
            for selected_model in selected_models
            for item in items
        ]
        self.id = uuid.uuid4().hex
        self.directory = Path(root) / "batches" / self.id
        self.directory.mkdir(parents=True)
        self.lock = threading.RLock()
        self.cancel_event = threading.Event()
        self.status = {
            "batch_id": self.id,
            "dataset": (
                next(iter({item["dataset"] for item in items}))
                if len({item["dataset"] for item in items}) == 1
                else "mixed"
            ),
            "datasets": sorted({item["dataset"] for item in items}),
            "state": "queued",
            "model": selected_models[0],
            "models": selected_models,
            "model_states": {name: "queued" for name in selected_models},
            "images_per_model": len(selections),
            "current_model": None,
            "ocr_profile": ocr_profile,
            "workers": workers,
            "backend": backend,
            "threads_per_worker": threads_per_worker(workers),
            "completed": 0,
            "total": len(items),
            "current_run_id": None,
            "items": items,
            "evaluation_policy": evaluation_policy(),
        }
        if detection_options:
            if "detection_evaluation" in self.status["datasets"]:
                detection_options = {**detection_options, "context": {}}
                self.status["detection_context_mode"] = "none"
            self.status["detection_options"] = detection_options
        self.save()
        self.pool = None

    def save(self):
        self.status["summary"] = summarize(
            [
                item
                for item in self.status["items"]
                if item.get("reference_available", True)
            ]
        )
        self.status["performance"] = performance_summary(self.status["items"])
        self.status["model_summaries"] = [
            {
                "model": name,
                "state": self.status.get("model_states", {}).get(
                    name, self.status["state"]
                ),
                "summary": summarize(
                    [
                        item
                        for item in self.status["items"]
                        if item.get("model", self.status["model"]) == name
                        and item.get("reference_available", True)
                    ]
                ),
                "performance": performance_summary(
                    [
                        item
                        for item in self.status["items"]
                        if item.get("model", self.status["model"]) == name
                    ]
                ),
            }
            for name in self.status.get("models", [self.status["model"]])
        ]
        if self.status.get("detection_options") and any(
            "cases" in item for item in self.status["items"]
        ):
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
            if self.pool is not None:
                self.pool.cancel()
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
        batch.pool = None
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
            for model in self.status.get("models", [self.status["model"]]):
                check_cancelled(self.cancel_event)
                backend = backend_for(
                    model, self.status.get("backend", DEFAULT_BACKEND)
                )
                workers = 1 if model in SINGLE_PASS_MODELS else self.status["workers"]
                with self.lock:
                    self.status["current_model"] = model
                    self.status.setdefault("model_states", {})[model] = "running"
                    self.save()
                with EnginePool(
                    model,
                    models,
                    workers,
                    backend,
                    engine_factory_for(
                        self.status.get("ocr_profile", "transforms"),
                        backend=backend,
                        workers=workers,
                        override=engine_factory,
                    ),
                ) as pool:
                    self.pool = pool
                    self._run_images(
                        root, models, catalog, jobs, pool, detection_service
                    )
                self.pool = None
                with self.lock:
                    records = [
                        item
                        for item in self.status["items"]
                        if item.get("model", self.status["model"]) == model
                    ]
                    self.status["model_states"][model] = (
                        "failed"
                        if all(item["state"] == "failed" for item in records)
                        else "completed"
                    )
                    self.save()
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
                for model, state in self.status.get("model_states", {}).items():
                    if state in {"running", "queued"}:
                        self.status["model_states"][model] = "cancelled"
                self.save()
        except Exception as error:
            with self.lock:
                self.status.update(state="failed", error=str(error))
                self.save()
        finally:
            self.pool = None

    def _run_images(self, root, models, catalog, jobs, pool, detection_service=None):
        for item in self.status["items"]:
            if (
                item.get("model", self.status["model"]) != pool.model
                or item["state"] != "queued"
            ):
                continue
            check_cancelled(self.cancel_event)
            started = time.perf_counter()
            store = RunStore(
                root,
                pool.model,
                workers=pool.workers,
                backend=pool.backend,
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
                item["cost"] = cost_for_result({"model": pool.model, "variants": []})
                self.status["current_run_id"] = store.id
                self.save()
            try:
                item_dataset = item.get(
                    "dataset", self.status.get("dataset", "ocr_evaluation")
                )
                item_catalog = (
                    catalog[item_dataset] if isinstance(catalog, dict) else catalog
                )
                reference = item_catalog.reference(item["dataset_id"])
                item["input_sha256"] = sha256(item_catalog.path(item["dataset_id"]))
                item["reference_sha256"] = reference_digest(reference)
                result = extract(
                    item_catalog.path(item["dataset_id"]),
                    pool.model,
                    store=store,
                    models_dir=models,
                    workers=pool.workers,
                    engine_pool=pool,
                    ocr_profile=self.status.get("ocr_profile", "transforms"),
                    reference=reference,
                    backend=pool.backend,
                    cancel_event=self.cancel_event,
                )
                evaluation = result.get("evaluation")
                detection_result = (
                    detection_service.enqueue(check_store, options).result()
                    if check_store
                    else None
                )
                with self.lock:
                    item.update(
                        state="running",
                        recognized_text=result.get("text", ""),
                        ocr_profile=result.get("ocr_profile"),
                        elapsed_seconds=result.get("elapsed_seconds"),
                        cost=result.get("cost"),
                        inference_seconds=sum(
                            step.get("preprocessing", {}).get(
                                "runtime_inference_seconds",
                                step.get("timing", {}).get("ocr_seconds", 0),
                            )
                            for step in result.get("variants", [])
                        ),
                        initialization_seconds=sum(
                            step.get("timing", {}).get("engine_acquire_seconds", 0)
                            + step.get("preprocessing", {}).get(
                                "runtime_initialization_seconds", 0
                            )
                            for step in result.get("variants", [])
                        ),
                    )
                    if evaluation:
                        item.update(
                            valid=evaluation["valid"],
                            coverage=evaluation["final"]["coverage"],
                            missing=evaluation["final"]["missing"],
                            exact_valid=evaluation["final"]["exact"]["valid"],
                            exact_coverage=evaluation["final"]["exact"]["coverage"],
                            exact_missing=evaluation["final"]["exact"]["missing"],
                            pipeline_coverage=evaluation["detection"]["coverage"],
                            final_valid=evaluation["final"]["valid"],
                            best_step_id=evaluation["best_step_id"],
                            effects=evaluation["effects"],
                        )
                    if result.get("evaluation_unavailable"):
                        item["scoring_unavailable"] = result["evaluation_unavailable"][
                            "reason"
                        ]
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
                    if isinstance(error, ModelInitializationError):
                        for pending in self.status["items"]:
                            if (
                                pending.get("model") == pool.model
                                and pending["state"] == "queued"
                            ):
                                pending.update(
                                    state="failed",
                                    error=f"Model initialization failed: {error}",
                                    cost=cost_for_result(
                                        {"model": pool.model, "variants": []}
                                    ),
                                )
                                self.status["completed"] += 1
                    for case in item.get("cases", []):
                        if case["state"] not in {"completed", "failed"}:
                            case.update(
                                state="failed", outcome="error", error=str(error)
                            )
            finally:
                with self.lock:
                    variants = store.snapshot()["variants"]
                    if variants:
                        item["cost"] = cost_for_result(
                            {"model": pool.model, "variants": variants}
                        )
                    item["scan_seconds"] = time.perf_counter() - started
                    if item.get("elapsed_seconds") is None:
                        item["elapsed_seconds"] = item["scan_seconds"]
                    if not self.cancel_event.is_set():
                        self.status["completed"] += 1
                    self.save()
            # Completed run events can be restored from disk on demand.
            jobs.pop(store.id, None)
