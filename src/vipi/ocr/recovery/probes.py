"""Recognize scaled OCR candidates and apply the measured retention guards."""

from copy import deepcopy
from dataclasses import asdict
import re
import time

from PIL import Image

from vipi.cancellation import check_cancelled
from vipi.ocr.models import sha256
from vipi.ocr.transforms import TWO_TIMES_MAX_PIXELS, View
from vipi.storage.files import write_json

from .decisions import read_choice
from .layout import LAYOUT_VERSION, group_reading
from .resolution_retention import repair_resolution_reading
from .upscale_retry import retained_confident_tokens


def recognize_scaled(original, factor, method, engine, store, attempts, cancel_event):
    """Append a scaled reading with geometry mapped to the original image.

    The caller decides whether to retain it. Full-page provider text is kept as
    returned; boxed local readings use the shared layout grouping.
    """
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


def recover_resolution(
    original, selected, selection, engine, decider, store, attempts, cancel_event
):
    """Review a guarded 2x reading, then apply supported 1.5x letter insertions.

    Update the existing selection record with decisions and applied corrections.
    Eligibility uses the confident regions present before either resolution probe.
    """
    decisions = selection["decisions"]
    confident_regions = any(
        isinstance(region.get("confidence"), (int, float))
        and not isinstance(region.get("confidence"), bool)
        and 0.9 <= region["confidence"] <= 1
        and re.search(r"\w", region.get("text", ""))
        for region in selected["step"].get("regions", [])
    )
    if (
        selection["routing"]["route"] != "no_signal"
        and selected["id"] == "0001"
        and confident_regions
        and original.width * original.height <= TWO_TIMES_MAX_PIXELS
    ):
        candidate = recognize_scaled(
            original, 2, "bicubic", engine, store, attempts, cancel_event
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
                selection.update(
                    stop_reason="guarded_upscale_improvement", review_action="accept"
                )

    if confident_regions:
        probe = recognize_scaled(
            original, 1.5, "lanczos", engine, store, attempts, cancel_event
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
        selection["resolution_changes"] = resolution_changes
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

    return selected
