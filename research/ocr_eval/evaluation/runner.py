"""Attach dataset evaluation to product OCR without importing research into it."""

from pathlib import Path

from vipi.ocr import pipeline
from vipi.ocr.models import DEFAULT_MODEL
from vipi.ocr.runtime import DEFAULT_BACKEND
from vipi.ocr.workers import DEFAULT_WORKERS
from vipi.storage.ocr import RunStore
from .metrics import evaluate
from .profiles import DEFAULT_PROFILE, engine_factory_for, validate_profile


def extract(
    image,
    model=DEFAULT_MODEL,
    on_event=None,
    *,
    reference=None,
    ocr_profile=DEFAULT_PROFILE,
    **options,
):
    from research.workbench.model_registry import SINGLE_PASS_MODELS
    from research.workbench.ocr_costs import cost_for_result

    validate_profile(ocr_profile)
    adaptive = ocr_profile == "adaptive-jev"
    if adaptive:
        options["workers"] = 1
    options["baseline"] = ocr_profile == "baseline"
    if options["baseline"] and options.get("engine_pool") is None:
        options["workers"] = 1
    if model in SINGLE_PASS_MODELS:
        options["single_pass"] = True
    if not any(
        options.get(key) is not None
        for key in ("engine", "engine_factory", "engine_pool")
    ):
        options["engine_factory"] = engine_factory_for(
            ocr_profile,
            backend=options.get("backend", DEFAULT_BACKEND),
            workers=options.get("workers", DEFAULT_WORKERS),
        )
    store = options.get("store")
    if store is None and reference is not None:
        store = RunStore(
            Path(options.get("runs_dir", "runs")),
            model,
            on_event,
            workers=options.get("workers", DEFAULT_WORKERS),
            backend=options.get("backend", DEFAULT_BACKEND),
        )
        options["store"] = store

    def attach(result):
        result["cost"] = cost_for_result(result)
        if reference is not None:
            if (
                not reference["reading_order_known"]
                and not result["regions"]
                and result["text"].strip()
            ):
                result["evaluation_unavailable"] = {
                    "reason": "This reference requires word locations; the model returned transcription without coordinates. Text is saved but spatial word coverage is unscored.",
                    "reference": reference,
                }
                return
            store.transition("evaluating", state="evaluating")
            result["evaluation"] = evaluate(
                reference,
                result["text"],
                result["regions"],
                result["variants"],
                include_effects=not adaptive,
            )
            if adaptive:
                evaluation = result["evaluation"]
                evaluation["first_attempt"] = evaluation["steps"][
                    result["variants"][0]["id"]
                ]
                original = next(
                    (
                        step
                        for step in result["variants"]
                        if step["plan"]
                        == {
                            "orientation": "upright",
                            "contrast": "unchanged",
                            "crop": "full",
                        }
                    ),
                    None,
                )
                evaluation["original"] = (
                    evaluation["steps"][original["id"]] if original else None
                )

    if adaptive:
        from .adaptive import extract as adaptive_extract

        options.pop("workers", None)
        options.pop("baseline", None)
        options.pop("single_pass", None)
        return adaptive_extract(image, model, on_event, on_result=attach, **options)
    return pipeline.extract(image, model, on_event, on_result=attach, **options)


def reassemble(run_id, *, runs_dir="runs"):
    import json
    import re

    if not re.fullmatch(r"[a-f0-9]{32}", run_id):
        raise ValueError("Invalid run ID.")
    saved = Path(runs_dir) / run_id / "result.json"
    if (
        saved.is_file()
        and json.loads(saved.read_text(encoding="utf-8")).get("ocr_profile")
        == "adaptive-jev"
    ):
        raise ValueError(
            "Adaptive runs retain a reviewed candidate; rerun extraction instead of replacing it with legacy assembly."
        )

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
