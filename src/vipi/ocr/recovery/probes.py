"""Recognize scaled OCR candidates and persist their source-coordinate evidence."""

from dataclasses import asdict
import time

from PIL import Image

from vipi.cancellation import check_cancelled
from vipi.ocr.models import sha256
from vipi.ocr.transforms import View
from vipi.storage.files import write_json

from .layout import LAYOUT_VERSION, group_reading


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
