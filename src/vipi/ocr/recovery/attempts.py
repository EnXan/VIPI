"""Build transformed OCR attempts and persist their native evidence."""

from dataclasses import asdict, replace
import time

import numpy as np

from vipi.cancellation import check_cancelled
from vipi.config import CLOUD_OCR_MODELS
from vipi.ocr.measured_transforms import orientation_view
from vipi.ocr.models import sha256
from vipi.ocr.transforms import apply_filter, render_view
from vipi.storage.files import write_json

from .layout import LAYOUT_VERSION, group_reading


def recovery_plans(orientation="upright"):
    """Distinct measured contrast mechanisms, ordered for an early useful result."""
    return [
        {"orientation": orientation, "contrast": name, "crop": "full"}
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


def recognize_plan(
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
