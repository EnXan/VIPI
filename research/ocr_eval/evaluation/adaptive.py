"""Bounded visual selection, native OCR and review, retaining every candidate."""

from concurrent.futures import CancelledError
from dataclasses import asdict, replace
from pathlib import Path
import time

import numpy as np

from vipi.cancellation import check_cancelled
from vipi.ocr.measured_transforms import orientation_view
from vipi.ocr.models import sha256
from vipi.ocr.transforms import apply_filter, decode_image, render_view
from vipi.storage.files import write_json
from vipi.storage.ocr import RunStore

from .layout import LAYOUT_VERSION, group_reading
from .transform_decisions import JevDecider, read_choice, read_plan

# The maintainer explicitly requested a second and third OCR attempt.
MAX_ATTEMPTS = 3
PROFILE = "adaptive-jev"


def view_for_plan(size, plan):
    view = orientation_view(*size, plan["orientation"])
    if plan["crop"] == "full":
        return view
    width_fraction, fraction = {
        "center-half": (1, 0.5),
        "center-quarter": (1, 0.25),
        "center-75x50": (0.75, 0.5),
        "center-50x50": (0.5, 0.5),
    }[plan["crop"]]
    left, right = (
        int(view.width * (0.5 - width_fraction / 2)),
        int(view.width * (0.5 + width_fraction / 2)),
    )
    top, bottom = (
        int(view.height * (0.5 - fraction / 2)),
        int(view.height * (0.5 + fraction / 2)),
    )
    translation = np.asarray(((1, 0, left), (0, 1, top), (0, 0, 1)))
    return replace(
        view,
        id=f"{view.id}-{plan['crop']}",
        height=bottom - top,
        width=right - left,
        crop=(left, top, right, bottom),
        to_input=tuple(map(tuple, np.asarray(view.to_input) @ translation)),
    )


def extract(
    image,
    model,
    on_event=None,
    *,
    engine=None,
    engine_factory=None,
    engine_pool=None,
    store=None,
    runs_dir="runs",
    models_dir="models/ocr",
    backend="cpu",
    cancel_event=None,
    on_result=None,
    decider=None,
):
    store = store or RunStore(
        Path(runs_dir), model, on_event, workers=1, backend=backend
    )
    decider = decider or JevDecider()
    started = time.perf_counter()
    attempts, decisions = [], []
    local_engine = None
    try:
        check_cancelled(cancel_event)
        original = decode_image(image)
        original.save(store.directory / "input.png")
        store.transition(
            "run_started",
            state="selecting",
            model=model,
            ocr_profile=PROFILE,
            total=MAX_ATTEMPTS,
            workers=1,
            input_size=list(original.size),
            active_steps={},
        )

        def decide():
            check_cancelled(cancel_event)
            number = len(decisions) + 1
            store.transition(
                "transformation_deciding",
                state="selecting",
                data={"decision": number, "attempts": len(attempts)},
            )
            record = decider.decide(
                original, attempts, store.directory / "decisions" / f"{number:04d}"
            )
            check_cancelled(cancel_event)
            decisions.append(record)
            write_json(store.directory / "decisions.json", decisions)
            return record["response"]

        response = decide()
        plan = read_plan(response)
        begin = time.perf_counter()
        if engine_pool is not None:
            local_engine = engine_pool.engine()
        elif engine is not None:
            local_engine = engine
        else:
            if engine_factory is None:
                from research.workbench.model_registry import create_engine

                def engine_factory(model, directory):
                    return create_engine(
                        model, directory, profile=PROFILE, backend=backend, threads=1
                    )

            local_engine = engine_factory(model, Path(models_dir))
        initialization_seconds = time.perf_counter() - begin
        best, stop_reason, review_action = None, None, None
        for index in range(1, MAX_ATTEMPTS + 1):
            check_cancelled(cancel_event)
            view = view_for_plan(original.size, plan)
            identifier = f"{index:04d}"
            current = {
                "id": identifier,
                "index": index,
                "worker_id": 1,
                "view_id": view.id,
                "filter": plan["contrast"],
                "width": view.width,
                "height": view.height,
                "label": f"{view.id} · {plan['contrast']}",
                "plan": plan,
                "image": f"images/{identifier}.png",
            }
            store.advance(1, "step_started", "transforming", current)
            begin = time.perf_counter()
            raster = apply_filter(render_view(original, view), plan["contrast"])
            transform_seconds = time.perf_counter() - begin
            raster.save(store.directory / current["image"])
            store.advance(1, "image_ready", "transforming", current)
            check_cancelled(cancel_event)
            store.advance(1, "ocr_started", "ocr", current)
            begin = time.perf_counter()
            recognized = local_engine.recognize(raster)
            ocr_seconds = time.perf_counter() - begin
            for region in recognized["regions"]:
                region["input_polygon"] = view.map_polygon(region["polygon"])
            step = {
                **current,
                **recognized,
                "transformation": asdict(view),
                "raster_sha256": sha256(store.directory / current["image"]),
                "timing": {
                    "transform_seconds": transform_seconds,
                    "ocr_seconds": ocr_seconds,
                    "engine_acquire_seconds": initialization_seconds
                    if index == 1
                    else 0,
                },
            }
            begin = time.perf_counter()
            if recognized.get("full_page_text") or not recognized["regions"]:
                text, groups = recognized["text"], []
            else:
                text, groups = group_reading(step, raster, view)
            step.update(
                grouped_text=text,
                groups=groups,
                layout_version=LAYOUT_VERSION,
                layout_seconds=time.perf_counter() - begin,
            )
            store.complete_step(1, step)
            attempts.append(
                {
                    "id": identifier,
                    "plan": plan,
                    "raster": raster,
                    "text": text,
                    "groups": groups,
                    "step": step,
                }
            )
            response = decide()
            review_action = read_choice(
                response, "action", ("accept", "retry", "uncertain")
            )
            best = read_choice(response, "best_attempt", {a["id"] for a in attempts})
            step["review"] = {
                "action": review_action,
                "best_attempt": best,
                "decision": len(decisions),
            }
            write_json(store.directory / "attempts.json", [a["step"] for a in attempts])
            if review_action != "retry":
                stop_reason = review_action
                break
            if index == MAX_ATTEMPTS:
                stop_reason = "attempt_limit"
                break
            plan = read_plan(response)
            if plan in [a["plan"] for a in attempts]:
                stop_reason = "repeated_plan"
                break
        selected = next(a for a in attempts if a["id"] == best)
        result = {
            "run_id": store.id,
            "model": model,
            "ocr_profile": PROFILE,
            "workers": 1,
            "backend": backend,
            "threads_per_worker": 1,
            "input_size": list(original.size),
            "text": selected["text"],
            "regions": selected["groups"],
            "variants": [a["step"] for a in attempts],
            "assembly_version": LAYOUT_VERSION,
            "preserve_raw_text": False,
            "full_page_text": bool(selected["step"].get("full_page_text")),
            "selection": {
                "model": decider.model,
                "selected_attempt": best,
                "stop_reason": stop_reason,
                "review_action": review_action,
                "accepted": review_action == "accept",
                "max_attempts": MAX_ATTEMPTS,
                "decisions": decisions,
            },
        }
        check_cancelled(cancel_event)
        if on_result:
            on_result(result)
        result["elapsed_seconds"] = time.perf_counter() - started
        write_json(store.directory / "result.json", result)
        (store.directory / "result.txt").write_text(result["text"], encoding="utf-8")
        store.transition(
            "run_completed",
            state="completed",
            current=None,
            active_steps={},
            total=len(attempts),
            completed=len(attempts),
            data={
                "text": result["text"],
                "regions": result["regions"],
                "evaluation": result.get("evaluation"),
                "selection": result["selection"],
            },
        )
        return result
    except CancelledError:
        store.transition(
            "run_cancelled", state="cancelled", active_steps={}, current=None
        )
        raise
    except (Exception, KeyboardInterrupt) as error:
        if engine_pool is not None and local_engine is not None:
            engine_pool.discard_engine()
        store.transition(
            "run_failed", state="failed", active_steps={}, error=str(error)
        )
        raise
    finally:
        if engine is None and engine_pool is None and local_engine is not None:
            close = getattr(local_engine, "close", None)
            if close:
                close()
