"""Experimental local re-recognition of low-confidence OCR words."""

from copy import deepcopy
import math
import re

from PIL import Image

from vipi.ocr.merge import bounds


def _intersection(a, b):
    return max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(
        0, min(a[3], b[3]) - max(a[1], b[1])
    )


def apply_approved(groups, changes, approved):
    """Apply only individually approved readings to their unique original group."""
    result = deepcopy(groups)
    applied = []
    for change, accept in zip(changes, approved, strict=True):
        if not accept:
            continue
        original = change["old"]
        box = change["box"]
        area = (box[2] - box[0]) * (box[3] - box[1])
        pattern = re.compile(r"(?<!\w)" + re.escape(original) + r"(?!\w)")
        matched = [
            g
            for g in result
            if g.get("box")
            and area > 0
            and _intersection(box, g["box"]) >= 0.5 * area
            and len(list(pattern.finditer(g["text"]))) == 1
        ]
        if len(matched) != 1:
            continue
        matched[0]["text"] = pattern.sub(
            lambda _: change["new"], matched[0]["text"], count=1
        )
        applied.append(change)
    return {
        "text": "\n".join(g["text"] for g in result),
        "regions": result,
        "changes": applied,
    }


def retry_regions(image, step, groups, engine):
    """Retry uniquely mapped weak words, accepting only a strong local reading.

    The thresholds are research hypotheses for one OCR model, not calibrated
    general defaults. Neither reference transcripts nor scores are inputs.
    """
    output = deepcopy(groups)
    changes, attempts = [], []
    for region in step.get("regions", []):
        original = region.get("text", "")
        confidence = region.get("confidence")
        if (
            len(original.strip()) < 3
            or isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or not 0 <= confidence < 0.5
            or not region.get("input_polygon")
        ):
            continue
        source_box = bounds(region["input_polygon"])
        area = (source_box[2] - source_box[0]) * (source_box[3] - source_box[1])
        if area <= 0:
            continue
        pattern = re.compile(r"(?<!\w)" + re.escape(original) + r"(?!\w)")
        matches = [
            i
            for i, group in enumerate(output)
            if group.get("box")
            and _intersection(source_box, group["box"]) >= 0.5 * area
            and len(list(pattern.finditer(group["text"]))) == 1
        ]
        if len(matches) != 1:
            continue
        padding = max(1, source_box[3] - source_box[1])
        left = max(0, math.floor(source_box[0] - padding))
        top = max(0, math.floor(source_box[1] - padding))
        right = min(image.width, math.ceil(source_box[2] + padding))
        bottom = min(image.height, math.ceil(source_box[3] + padding))
        if right <= left or bottom <= top:
            continue
        crop = image.crop((left, top, right, bottom))
        crop = crop.resize((crop.width * 2, crop.height * 2), Image.Resampling.LANCZOS)
        result = engine.recognize(crop)
        scaled_box = tuple(
            2 * (value - offset)
            for value, offset in zip(source_box, (left, top, left, top), strict=True)
        )
        found = []
        for candidate in result.get("regions", []):
            if not candidate.get("polygon"):
                continue
            cbox = bounds(candidate["polygon"])
            carea = (cbox[2] - cbox[0]) * (cbox[3] - cbox[1])
            score = candidate.get("confidence")
            text = candidate.get("text", "").strip()
            if (
                carea > 0
                and _intersection(cbox, scaled_box) >= 0.5 * min(carea, area * 4)
                and isinstance(score, (float, int))
                and not isinstance(score, bool)
                and 0 <= score <= 1
                and text
                and not any(c.isspace() for c in text)
            ):
                found.append((float(score), text))
        attempts.append(
            {"text": original, "confidence": confidence, "candidates": found}
        )
        if len(found) != 1:
            continue
        new_confidence, text = found[0]
        if (
            text == original
            or new_confidence < 0.9
            or new_confidence - confidence < 0.2
        ):
            continue
        group = output[matches[0]]
        group["text"] = pattern.sub(lambda _: text, group["text"], count=1)
        changes.append(
            {
                "old": original,
                "new": text,
                "old_confidence": confidence,
                "new_confidence": new_confidence,
                "box": list(source_box),
            }
        )
    return {
        "text": "\n".join(g["text"] for g in output),
        "regions": output,
        "attempts": attempts,
        "changes": changes,
    }
