"""Experimental spatial evidence for potentially missed OCR text."""

from collections import defaultdict
import math

from PIL import Image

from vipi.ocr.merge import bounds
from vipi.ocr.transforms import apply_filter


def _box(region):
    try:
        polygon = region.get("input_polygon")
        if not polygon:
            return None
        box = bounds(polygon)
        if not all(math.isfinite(float(v)) for v in box):
            return None
        return box if box[2] > box[0] and box[3] > box[1] else None
    except (TypeError, ValueError):
        return None


def _intersection(a, b):
    return max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(
        0, min(a[3], b[3]) - max(a[1], b[1])
    )


def find_uncovered(incumbent_regions, candidate_regions):
    """Group candidate words lacking an incumbent detection at their location.

    Thresholds are exploratory: 0.8 candidate OCR confidence, two non-space
    characters, and less than 25% overlap with any incumbent region. This is
    not a text detector, proof that text is absent, or a security verdict.
    """
    old = [box for r in incumbent_regions if (box := _box(r)) is not None]
    if len(old) != len(incumbent_regions):
        raise ValueError("Incumbent OCR region geometry unavailable")
    if any(_box(region) is None for region in candidate_regions):
        raise ValueError("Candidate OCR region geometry unavailable")
    lines = defaultdict(list)
    for index, region in enumerate(candidate_regions):
        box = _box(region)
        confidence = region.get("confidence")
        text = region.get("text", "").strip()
        if (
            box is None
            or isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or not 0.8 <= confidence <= 1
            or len(text) < 2
        ):
            continue
        area = (box[2] - box[0]) * (box[3] - box[1])
        overlap = max((_intersection(box, b) / area for b in old), default=0)
        if overlap < 0.25:
            key = region.get("line_id")
            lines[("line", str(key)) if key is not None else ("region", index)].append(
                {"text": text, "box": list(box), "confidence": confidence}
            )
    result = []
    for words in lines.values():
        result.append(
            {
                "text": " ".join(word["text"] for word in words),
                "box": [
                    min(w["box"][0] for w in words),
                    min(w["box"][1] for w in words),
                    max(w["box"][2] for w in words),
                    max(w["box"][3] for w in words),
                ],
                "words": words,
            }
        )
    return result


def recognize_uncovered(image, lines, engine):
    """Independently reread suspect boxes; retain source and geometry per reading."""
    readings = []
    for index, line in enumerate(lines):
        x1, y1, x2, y2 = line["box"]
        padding = max(1, y2 - y1)
        box = (
            max(0, math.floor(x1 - padding)),
            max(0, math.floor(y1 - padding)),
            min(image.width, math.ceil(x2 + padding)),
            min(image.height, math.ceil(y2 + padding)),
        )
        if box[2] <= box[0] or box[3] <= box[1]:
            continue
        source = image.crop(box).convert("RGB")
        for method in ("upscale-2x", "green-minus-red-2x"):
            crop = (
                apply_filter(source, "green-minus-red")
                if method.startswith("green")
                else source
            )
            crop = crop.resize(
                (crop.width * 2, crop.height * 2), Image.Resampling.BICUBIC
            )
            result = engine.recognize(crop)
            regions = []
            for region in result.get("regions", []):
                if not region.get("polygon"):
                    continue
                mapped = [
                    [x / 2 + box[0], y / 2 + box[1]] for x, y in region["polygon"]
                ]
                regions.append({**region, "input_polygon": mapped})
            readings.append(
                {
                    "source": method,
                    "source_line": index,
                    "crop_box": list(box),
                    "text": result.get("text", ""),
                    "regions": regions,
                }
            )
    return readings
