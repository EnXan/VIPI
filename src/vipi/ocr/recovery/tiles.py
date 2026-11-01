"""Retry spatial OCR with source-resolution tiles and retain existing words."""

from collections import Counter
from copy import deepcopy
from dataclasses import asdict
import re
import time

import numpy as np

from vipi.cancellation import check_cancelled
from vipi.ocr.merge import ASSEMBLY_VERSION, assemble, bounds
from vipi.ocr.models import sha256
from vipi.ocr.transforms import View, tile_starts
from vipi.storage.files import write_json

from .upscale_retry import retained_confident_tokens

TILE_SIZE = 1024
TILE_CONFIDENCE = 0.8
SMALL_TEXT_HEIGHT = 12
LARGE_IMAGE_SIDE = 2000


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
