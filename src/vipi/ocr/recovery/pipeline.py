"""Coordinate original OCR, correction review, resolution recovery and completion."""

from concurrent.futures import CancelledError
from dataclasses import asdict, replace
from pathlib import Path
import time

import numpy as np

from vipi.cancellation import check_cancelled
from vipi.config import CLOUD_OCR_MODELS
from vipi.ocr.measured_transforms import orientation_view
from vipi.ocr.merge import ASSEMBLY_VERSION
from vipi.ocr.models import sha256
from vipi.ocr.transforms import (
    apply_filter,
    decode_image,
    render_view,
)
from vipi.storage.files import write_json
from vipi.storage.ocr import RunStore

from .decisions import DecisionsDecider, read_choice
from .extended_signals import RECOVERY_PARAMETERS, route_extended
from .layout import LAYOUT_VERSION, group_reading
from .probes import recover_resolution
from .tiles import recover_with_tiles

PROFILE = "adaptive-jev"


def recovery_plans():
    """Distinct measured contrast mechanisms, ordered for an early useful result."""
    return [
        {"orientation": "upright", "contrast": name, "crop": "full"}
        for name in ("green-minus-red", "saturation-inverted", "saturation-clahe")
    ]


def view_for_plan(size, plan):
    """Map an orientation and optional centered crop to source coordinates."""
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


def _recognize_plan(
    original,
    plan,
    engine,
    store,
    attempts,
    *,
    model,
    cancel_event,
    initialization_seconds=0,
):
    """Append one transformed OCR attempt and persist its native and grouped text."""
    index = len(attempts) + 1
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
    recognized = engine.recognize(raster)
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
            "engine_acquire_seconds": initialization_seconds if index == 1 else 0,
        },
    }
    begin = time.perf_counter()
    if model in CLOUD_OCR_MODELS:
        recognized["full_page_text"] = True
        step["full_page_text"] = True
    if recognized.get("full_page_text") or not recognized["regions"]:
        text, groups = recognized["text"], recognized["regions"]
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
    write_json(store.directory / "attempts.json", [a["step"] for a in attempts])
    return attempts[-1]


def _correction_plans(original, selected, decider, store, selection, cancel_event):
    """Record the original assessment and return its chosen correction plans."""
    decisions = selection["decisions"]
    check_cancelled(cancel_event)
    store.transition("ocr_assessing", state="selecting", data={"decision": 1})
    record = decider.assess(original, selected, store.directory / "decisions" / "0001")
    check_cancelled(cancel_event)
    assessment = read_choice(
        record["response"],
        "assessment",
        ("ready", "orientation", "contrast", "uncertain"),
    )
    selection["assessment"] = assessment
    decisions.append({"kind": "assessment", **record})
    write_json(store.directory / "decisions.json", decisions)

    # Empty OCR never proves absence of hidden low-contrast text.
    route = "contrast" if not selected["text"].strip() else assessment
    if route == "ready":
        selection.update(stop_reason="original_ready", review_action="accept")
        return []
    if route == "uncertain":
        selection["stop_reason"] = "assessment_uncertain"
        return []
    if route == "contrast":
        return recovery_plans()

    check_cancelled(cancel_event)
    store.transition("orientation_selecting", state="selecting", data={"decision": 2})
    orientation, record = decider.choose_orientation(
        original, store.directory / "decisions" / "0002"
    )
    check_cancelled(cancel_event)
    decisions.append({"kind": "orientation_selection", **record})
    write_json(store.directory / "decisions.json", decisions)
    if orientation in {"upright", "uncertain"}:
        return []
    return [{"orientation": orientation, "contrast": "unchanged", "crop": "full"}]


def _compare_correction(
    original, selected, candidate, decider, store, attempts, decisions, cancel_event
):
    """Record a correction review, skipping empty or unchanged candidate text."""
    if not candidate["text"].strip() or candidate["text"] == selected["text"]:
        candidate["step"]["review"] = {
            "comparison": "skipped_no_new_text",
            "incumbent": selected["id"],
        }
        write_json(store.directory / "attempts.json", [a["step"] for a in attempts])
        return None
    check_cancelled(cancel_event)
    number = len(decisions) + 1
    store.transition(
        "transformation_deciding",
        state="selecting",
        data={
            "decision": number,
            "incumbent": selected["id"],
            "candidate": candidate["id"],
        },
    )
    record = decider.compare(
        original, selected, candidate, store.directory / "decisions" / f"{number:04d}"
    )
    check_cancelled(cancel_event)
    outcome = read_choice(
        record["response"],
        "comparison",
        ("improved", "equivalent", "worse", "uncertain"),
    )
    review = {
        "incumbent": selected["id"],
        "candidate": candidate["id"],
        "comparison": outcome,
        "decision": number,
    }
    decisions.append({**record, **review})
    candidate["step"]["review"] = review
    write_json(store.directory / "decisions.json", decisions)
    write_json(store.directory / "attempts.json", [a["step"] for a in attempts])
    return outcome


def _select_reading(
    original,
    model,
    engine,
    decider,
    store,
    attempts,
    initialization_seconds,
    cancel_event,
):
    """Read the original, then retain the first independently verified correction."""
    selected = _recognize_plan(
        original,
        {"orientation": "upright", "contrast": "unchanged", "crop": "full"},
        engine,
        store,
        attempts,
        model=model,
        cancel_event=cancel_event,
        initialization_seconds=initialization_seconds,
    )
    routing = route_extended(
        selected["text"],
        selected["step"]["regions"],
        selected["groups"],
        original,
        RECOVERY_PARAMETERS,
    )
    selection = {
        "stop_reason": "no_verified_improvement",
        "review_action": "uncertain",
        "planned_candidates": 1,
        "assessment": None,
        "selection_version": "gated-ocr-correction-v1",
        "routing": routing,
        "resolution_changes": [],
        "decisions": [],
    }
    if routing["route"] == "no_signal":
        selection.update(stop_reason="no_signal", review_action="not_required")
        return selected, selection

    plans = _correction_plans(
        original, selected, decider, store, selection, cancel_event
    )
    selection["planned_candidates"] += len(plans)
    if not plans:
        return selected, selection
    route = "contrast" if not selected["text"].strip() else selection["assessment"]
    store.transition(
        "corrections_planned",
        state="transforming",
        total=selection["planned_candidates"],
        data={"route": route},
    )
    for plan in plans:
        candidate = _recognize_plan(
            original,
            plan,
            engine,
            store,
            attempts,
            model=model,
            cancel_event=cancel_event,
        )
        outcome = _compare_correction(
            original,
            selected,
            candidate,
            decider,
            store,
            attempts,
            selection["decisions"],
            cancel_event,
        )
        if outcome == "improved":
            selection.update(stop_reason="verified_improvement", review_action="accept")
            return candidate, selection
    return selected, selection


def _complete_run(
    original,
    selected,
    selection,
    attempts,
    engine,
    decider,
    store,
    *,
    model,
    backend,
    cancel_event,
    on_result,
    started,
):
    """Merge source tiles, attach optional evaluation, and persist a completed run."""
    write_json(store.directory / "decisions.json", selection["decisions"])
    final_text, final_regions, tile_attempts, tile_recovery = recover_with_tiles(
        original, selected, engine, store, attempts, cancel_event
    )
    all_attempts = [*attempts, *tile_attempts]
    full_page_text = bool(selected["step"].get("full_page_text"))
    if tile_recovery["selected"]:
        assembly_version = ASSEMBLY_VERSION
    elif final_regions and not full_page_text:
        assembly_version = LAYOUT_VERSION
    else:
        assembly_version = None
    result = {
        "run_id": store.id,
        "model": model,
        "ocr_profile": PROFILE,
        "workers": 1,
        "backend": backend,
        "threads_per_worker": 1,
        "input_size": list(original.size),
        "text": final_text,
        "regions": final_regions,
        "variants": [a["step"] for a in all_attempts],
        "assembly_version": assembly_version,
        "preserve_raw_text": (full_page_text or not bool(final_regions))
        and not tile_recovery["selected"],
        "full_page_text": full_page_text,
        "selection": {
            "provider": decider.provider,
            "model": decider.model,
            "selected_attempt": selected["id"],
            **selection,
            "accepted": selection["review_action"] == "accept",
            "candidate_count": len(attempts),
            "tile_recovery": tile_recovery,
        },
    }
    from vipi.ocr.costs import cost_for_result

    result["cost"] = cost_for_result(result)
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
        total=len(all_attempts),
        completed=len(all_attempts),
        data={
            "text": result["text"],
            "regions": result["regions"],
            "evaluation": result.get("evaluation"),
            "selection": result["selection"],
        },
    )
    return result


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
    """Recognize and review OCR candidates, then save the selected reading.

    Engines return native text and regions; the decider assesses image defects
    and compares actual readings. Spatial retries retain incumbent words.
    ``on_result`` can attach evaluation after selection, before persistence.
    Failed and cancelled runs retain completed steps in the supplied run store.
    """
    store = store or RunStore(
        Path(runs_dir), model, on_event, workers=1, backend=backend
    )
    decider = decider or DecisionsDecider()
    started = time.perf_counter()
    attempts = []
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
            total=1,
            workers=1,
            input_size=list(original.size),
            active_steps={},
        )
        begin = time.perf_counter()
        if engine_pool is not None:
            local_engine = engine_pool.engine()
        elif engine is not None:
            local_engine = engine
        elif engine_factory is not None:
            local_engine = engine_factory(model, Path(models_dir))
        else:
            from vipi.ocr.engines import create_engine

            local_engine = create_engine(
                model,
                Path(models_dir),
                native_pipeline=True,
                backend=backend,
                threads=1,
            )
        initialization_seconds = time.perf_counter() - begin
        selected, selection = _select_reading(
            original,
            model,
            local_engine,
            decider,
            store,
            attempts,
            initialization_seconds,
            cancel_event,
        )
        selected = recover_resolution(
            original,
            selected,
            selection,
            local_engine,
            decider,
            store,
            attempts,
            cancel_event,
        )
        return _complete_run(
            original,
            selected,
            selection,
            attempts,
            local_engine,
            decider,
            store,
            model=model,
            backend=backend,
            cancel_event=cancel_event,
            on_result=on_result,
            started=started,
        )
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
