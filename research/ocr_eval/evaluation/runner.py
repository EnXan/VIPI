"""Attach dataset evaluation to product OCR without importing research into it."""

from pathlib import Path

from vipi.ocr import pipeline
from vipi.ocr.models import DEFAULT_MODEL
from vipi.ocr.runtime import DEFAULT_BACKEND
from vipi.ocr.workers import DEFAULT_WORKERS
from vipi.storage.ocr import RunStore
from .metrics import evaluate


def extract(image, model=DEFAULT_MODEL, on_event=None, *, reference=None, **options):
    if reference is None:
        return pipeline.extract(image, model, on_event, **options)
    store = options.get("store")
    if store is None:
        store = RunStore(
            Path(options.get("runs_dir", "runs")),
            model,
            on_event,
            workers=options.get("workers", DEFAULT_WORKERS),
            backend=options.get("backend", DEFAULT_BACKEND),
        )
        options["store"] = store

    def attach(result):
        store.transition("evaluating", state="evaluating")
        result["evaluation"] = evaluate(
            reference, result["text"], result["regions"], result["variants"]
        )

    return pipeline.extract(image, model, on_event, on_result=attach, **options)


def reassemble(run_id, *, runs_dir="runs"):
    def attach(result):
        previous = result.get("evaluation")
        if previous:
            result["evaluation"] = evaluate(
                previous["reference"],
                result["text"],
                result["regions"],
                result["variants"],
            )

    return pipeline.reassemble(run_id, runs_dir=runs_dir, on_result=attach)
