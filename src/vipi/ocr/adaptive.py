"""Assess original OCR once, then recognize targeted corrections only if needed."""

from collections import Counter
from copy import deepcopy
from concurrent.futures import CancelledError
from dataclasses import asdict, replace
from pathlib import Path
import re
import time

import numpy as np
from PIL import Image

from vipi.cancellation import check_cancelled
from vipi.ocr.measured_transforms import orientation_view
from vipi.ocr.merge import ASSEMBLY_VERSION, assemble, bounds
from vipi.ocr.models import sha256
from vipi.ocr.transforms import (
    View,
    apply_filter,
    decode_image,
    render_view,
    tile_starts,
)
from vipi.storage.files import write_json
from vipi.storage.ocr import RunStore

from .layout import LAYOUT_VERSION, group_reading
from .transform_decisions import DecisionsDecider, read_choice
from .extended_signals import BALANCED_EXPERIMENTAL_PARAMETERS, route_extended
from .resolution_retention import repair_resolution_reading
from .upscale_retry import retained_confident_tokens
from .transforms import TWO_TIMES_MAX_PIXELS
from vipi.config import CLOUD_OCR_MODELS

PROFILE = "adaptive-jev"
TILE_SIZE = 1024
TILE_CONFIDENCE = 0.8
SMALL_TEXT_HEIGHT = 12
LARGE_IMAGE_SIDE = 2000


def recovery_plans():
    """Distinct measured contrast mechanisms, ordered for an early useful result."""
    return [
        {"orientation": "upright", "contrast": name, "crop": "full"}
        for name in ("green-minus-red", "saturation-inverted", "saturation-clahe")
    ]


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


def recover_with_tiles(original, selected, engine, store, attempts, cancel_event):
    """Retry large or confidently detected small text with source-resolution tiles."""
    step = deepcopy(selected["step"])
    step["text"] = selected["text"]
    large_image = max(original.size) > LARGE_IMAGE_SIDE

    def is_small_text(region):
        polygon = region.get("input_polygon")
        confidence = region.get("confidence")
        if (
            not polygon
            or isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or confidence < TILE_CONFIDENCE
        ):
            return False
        _, top, _, bottom = bounds(polygon)
        return bottom - top < SMALL_TEXT_HEIGHT

    small_text = any(is_small_text(region) for region in step.get("regions", []))
    signals = {
        "large_image": large_image,
        "small_text": small_text,
        "triggered": large_image or small_text,
        "selected": False,
        "tile_count": 0,
    }
    if not signals["triggered"]:
        return selected["text"], selected["groups"], [], signals
    if not any(region.get("input_polygon") for region in step.get("regions", [])):
        signals["skipped"] = "spatial_ocr_regions_unavailable"
        return selected["text"], selected["groups"], [], signals
    if step.get("full_page_text"):
        try:
            retained_confident_tokens(step["regions"], "")
        except ValueError:
            signals["skipped"] = "full_page_geometry_has_no_confident_tokens"
            return selected["text"], selected["groups"], [], signals

    raster = original
    width, height = raster.size
    locations = [
        (x, y, min(TILE_SIZE, width), min(TILE_SIZE, height))
        for y in tile_starts(height)
        for x in tile_starts(width)
    ]
    signals["tile_count"] = len(locations)
    signals["assembly_version"] = ASSEMBLY_VERSION
    store.transition(
        "tile_recovery_planned",
        state="transforming",
        total=len(attempts) + len(locations),
        data={"tile_recovery": signals},
    )

    tile_attempts = []
    for x, y, tile_width, tile_height in locations:
        check_cancelled(cancel_event)
        identifier = f"{len(attempts) + len(tile_attempts) + 1:04d}"
        matrix = np.asarray(((1, 0, x), (0, 1, y), (0, 0, 1)), dtype=float)
        view = View(
            id=f"tile-1x-{x}-{y}",
            width=tile_width,
            height=tile_height,
            to_input=tuple(map(tuple, matrix)),
            backend="tile",
            method="native",
            crop=(x, y, x + tile_width, y + tile_height),
            factor=1,
        )
        current = {
            "id": identifier,
            "index": int(identifier),
            "worker_id": 1,
            "view_id": view.id,
            "filter": "unchanged",
            "width": tile_width,
            "height": tile_height,
            "label": f"{view.id} · source-resolution tile",
            "plan": {
                "orientation": "selected",
                "contrast": "unchanged",
                "crop": "tile",
            },
            "image": f"images/{identifier}.png",
        }
        store.advance(1, "step_started", "transforming", current)
        crop = raster.crop((x, y, x + tile_width, y + tile_height))
        image_path = store.directory / current["image"]
        crop.save(image_path)
        store.advance(1, "image_ready", "transforming", current)
        check_cancelled(cancel_event)
        store.advance(1, "ocr_started", "ocr", current)
        started = time.perf_counter()
        recognized = engine.recognize(crop)
        ocr_seconds = time.perf_counter() - started
        for region in recognized["regions"]:
            region["input_polygon"] = view.map_polygon(region["polygon"])
        tile_step = {
            **current,
            **recognized,
            "transformation": asdict(view),
            "raster_sha256": sha256(image_path),
            "timing": {"transform_seconds": 0, "ocr_seconds": ocr_seconds},
        }
        store.complete_step(1, tile_step)
        tile_attempts.append({"id": identifier, "step": tile_step})
        write_json(
            store.directory / "attempts.json",
            [attempt["step"] for attempt in [*attempts, *tile_attempts]],
        )

    store.transition("tile_recovery_assembling", state="assembling")
    candidate_text, candidate_regions = assemble(
        [step, *(attempt["step"] for attempt in tile_attempts)]
    )
    old_words = Counter(re.findall(r"\w+", selected["text"].casefold(), re.UNICODE))
    new_words = Counter(re.findall(r"\w+", candidate_text.casefold(), re.UNICODE))
    try:
        missing_confident = retained_confident_tokens(
            step.get("regions", []), candidate_text
        )
    except ValueError:
        missing_confident = ["<no_confident_tokens>"]
    signals["missing_confident_tokens"] = missing_confident
    signals["selected"] = not missing_confident and not (old_words - new_words)
    if signals["selected"]:
        return candidate_text, candidate_regions, tile_attempts, signals
    return selected["text"], selected["groups"], tile_attempts, signals


def recognize_scaled(original, factor, method, engine, store, attempts, cancel_event):
    check_cancelled(cancel_event)
    identifier = f"{len(attempts) + 1:04d}"
    width, height = round(original.width * factor), round(original.height * factor)
    view = View(
        id=f"{method}-{factor:g}x",
        width=width,
        height=height,
        to_input=(
            (original.width / width, 0, 0),
            (0, original.height / height, 0),
            (0, 0, 1),
        ),
        backend="pillow",
        method=method,
        factor=factor,
    )
    current = {
        "id": identifier,
        "index": int(identifier),
        "worker_id": 1,
        "view_id": view.id,
        "filter": "unchanged",
        "width": width,
        "height": height,
        "label": view.id,
        "image": f"images/{identifier}.png",
        "plan": {
            "orientation": "upright",
            "contrast": "unchanged",
            "crop": "full",
            "scale": factor,
        },
    }
    store.transition("resolution_planned", total=len(attempts) + 1)
    store.advance(1, "step_started", "transforming", current)
    started = time.perf_counter()
    raster = original.resize((width, height), getattr(Image.Resampling, method.upper()))
    raster.save(store.directory / current["image"])
    transform_seconds = time.perf_counter() - started
    store.advance(1, "image_ready", "transforming", current)
    store.advance(1, "ocr_started", "ocr", current)
    started = time.perf_counter()
    recognized = engine.recognize(raster)
    if recognized.get("preprocessing", {}).get("backend") == "api":
        recognized["full_page_text"] = True
    for region in recognized["regions"]:
        region["input_polygon"] = view.map_polygon(region["polygon"])
    step = {
        **current,
        **recognized,
        "transformation": asdict(view),
        "raster_sha256": sha256(store.directory / current["image"]),
        "timing": {
            "transform_seconds": transform_seconds,
            "ocr_seconds": time.perf_counter() - started,
        },
    }
    text, groups = (
        (recognized["text"], recognized["regions"])
        if not recognized["regions"] or recognized.get("full_page_text")
        else group_reading(step, raster, view)
    )
    step.update(grouped_text=text, groups=groups, layout_version=LAYOUT_VERSION)
    store.complete_step(1, step)
    attempt = {
        "id": identifier,
        "step": step,
        "raster": raster,
        "text": text,
        "groups": groups,
        "plan": current["plan"],
    }
    attempts.append(attempt)
    write_json(store.directory / "attempts.json", [a["step"] for a in attempts])
    return attempt


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
    decider = decider or DecisionsDecider()
    started = time.perf_counter()
    attempts, decisions = [], []
    local_engine = None
    plans = [{"orientation": "upright", "contrast": "unchanged", "crop": "full"}]
    selected = None
    gate_outcome = None
    routing = None
    resolution_changes = []
    stop_reason = "no_verified_improvement"
    review_action = "uncertain"
    try:
        check_cancelled(cancel_event)
        original = decode_image(image)
        original.save(store.directory / "input.png")
        store.transition(
            "run_started",
            state="selecting",
            model=model,
            ocr_profile=PROFILE,
            total=len(plans),
            workers=1,
            input_size=list(original.size),
            active_steps={},
        )

        begin = time.perf_counter()
        if engine_pool is not None:
            local_engine = engine_pool.engine()
        elif engine is not None:
            local_engine = engine
        else:
            if engine_factory is None:
                from .engines import create_engine

                def engine_factory(model, directory):
                    return create_engine(
                        model,
                        directory,
                        native_pipeline=True,
                        backend=backend,
                        threads=1,
                    )

            local_engine = engine_factory(model, Path(models_dir))
        initialization_seconds = time.perf_counter() - begin
        for index, plan in enumerate(plans, 1):
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

            if index == 1:
                selected = attempts[0]
                routing = route_extended(
                    selected["text"],
                    step["regions"],
                    selected["groups"],
                    original,
                    BALANCED_EXPERIMENTAL_PARAMETERS,
                )
                if routing["route"] == "no_signal":
                    stop_reason, review_action = "no_signal", "not_required"
                    break
                check_cancelled(cancel_event)
                store.transition(
                    "ocr_assessing", state="selecting", data={"decision": 1}
                )
                record = decider.assess(
                    original, selected, store.directory / "decisions" / "0001"
                )
                check_cancelled(cancel_event)
                gate_outcome = read_choice(
                    record["response"],
                    "assessment",
                    ("ready", "orientation", "contrast", "uncertain"),
                )
                decisions.append({"kind": "assessment", **record})
                write_json(store.directory / "decisions.json", decisions)
                # Empty OCR never proves absence of hidden low-contrast text.
                route = "contrast" if not selected["text"].strip() else gate_outcome
                if route == "ready":
                    stop_reason, review_action = "original_ready", "accept"
                    break
                if route == "uncertain":
                    stop_reason = "assessment_uncertain"
                    break
                if route == "orientation":
                    check_cancelled(cancel_event)
                    store.transition(
                        "orientation_selecting", state="selecting", data={"decision": 2}
                    )
                    orientation, record = decider.choose_orientation(
                        original, store.directory / "decisions" / "0002"
                    )
                    check_cancelled(cancel_event)
                    decisions.append({"kind": "orientation_selection", **record})
                    write_json(store.directory / "decisions.json", decisions)
                    if orientation in {"upright", "uncertain"}:
                        break
                    plans.append(
                        {
                            "orientation": orientation,
                            "contrast": "unchanged",
                            "crop": "full",
                        }
                    )
                else:
                    plans.extend(recovery_plans())
                store.transition(
                    "corrections_planned",
                    state="transforming",
                    total=len(plans),
                    data={"route": route},
                )
                continue

            candidate = attempts[-1]
            if not candidate["text"].strip() or candidate["text"] == selected["text"]:
                candidate["step"]["review"] = {
                    "comparison": "skipped_no_new_text",
                    "incumbent": selected["id"],
                }
                write_json(
                    store.directory / "attempts.json", [a["step"] for a in attempts]
                )
                continue
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
                original,
                selected,
                candidate,
                store.directory / "decisions" / f"{number:04d}",
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
            if outcome == "improved":
                selected = candidate
                stop_reason, review_action = "verified_improvement", "accept"
                break

        confident_regions = any(
            isinstance(region.get("confidence"), (int, float))
            and not isinstance(region.get("confidence"), bool)
            and 0.9 <= region["confidence"] <= 1
            and re.search(r"\w", region.get("text", ""))
            for region in selected["step"].get("regions", [])
        )
        if (
            routing["route"] != "no_signal"
            and selected["id"] == "0001"
            and confident_regions
            and original.width * original.height <= TWO_TIMES_MAX_PIXELS
        ):
            candidate = recognize_scaled(
                original, 2, "bicubic", local_engine, store, attempts, cancel_event
            )
            if candidate["text"].strip() and candidate["text"] != selected["text"]:
                number = len(decisions) + 1
                record = decider.compare(
                    original,
                    selected,
                    candidate,
                    store.directory / "decisions" / f"{number:04d}",
                )
                outcome = read_choice(
                    record["response"],
                    "comparison",
                    ("improved", "equivalent", "worse", "uncertain"),
                )
                try:
                    missing = retained_confident_tokens(
                        selected["step"]["regions"], candidate["text"]
                    )
                except ValueError:
                    missing = ["<no_confident_tokens>"]
                decisions.append(
                    {
                        "kind": "upscale_comparison",
                        **record,
                        "comparison": outcome,
                        "lost_confident_tokens": missing,
                    }
                )
                if outcome == "improved" and not missing:
                    selected = candidate
                    stop_reason, review_action = "guarded_upscale_improvement", "accept"

        if confident_regions:
            probe = recognize_scaled(
                original, 1.5, "lanczos", local_engine, store, attempts, cancel_event
            )
            try:
                fixed = repair_resolution_reading(
                    selected["groups"],
                    selected["step"]["regions"],
                    probe["step"]["regions"],
                    probe["text"],
                )
            except ValueError:
                fixed = {"changes": []}
            resolution_changes = fixed["changes"]
            if resolution_changes:
                selected = {
                    **selected,
                    "text": fixed["text"],
                    "groups": fixed["regions"],
                    "step": deepcopy(selected["step"]),
                }
                for change in resolution_changes:
                    for region in selected["step"]["regions"]:
                        if (
                            region["text"] == change["old"]
                            and region.get("input_polygon") == change["input_polygon"]
                        ):
                            region["text"] = change["new"]
                selected["step"]["text"] = selected["text"]

        write_json(store.directory / "decisions.json", decisions)
        best = selected["id"]
        final_text, final_regions, tile_attempts, tile_recovery = recover_with_tiles(
            original, selected, local_engine, store, attempts, cancel_event
        )
        all_attempts = [*attempts, *tile_attempts]
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
            "assembly_version": ASSEMBLY_VERSION
            if tile_recovery["selected"]
            else LAYOUT_VERSION
            if final_regions and not selected["step"].get("full_page_text")
            else None,
            "preserve_raw_text": (
                bool(selected["step"].get("full_page_text")) or not bool(final_regions)
            )
            and not tile_recovery["selected"],
            "full_page_text": bool(selected["step"].get("full_page_text")),
            "selection": {
                "provider": decider.provider,
                "model": decider.model,
                "selected_attempt": best,
                "stop_reason": stop_reason,
                "review_action": review_action,
                "accepted": review_action == "accept",
                "candidate_count": len(attempts),
                "planned_candidates": len(plans),
                "assessment": gate_outcome,
                "selection_version": "gated-ocr-correction-v1",
                "tile_recovery": tile_recovery,
                "routing": routing,
                "resolution_changes": resolution_changes,
                "decisions": decisions,
            },
        }
        from .costs import cost_for_result

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
