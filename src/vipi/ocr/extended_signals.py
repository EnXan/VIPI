"""Experimental additional local signals for the priority cascade.

Thresholds are hypotheses for a development comparison, not production policy.
"""

from dataclasses import asdict, dataclass
import math
import time
import unicodedata

import numpy as np
from .signals import Parameters, Signal, evidence


@dataclass(frozen=True)
class ExtendedParameters:
    regional_confidence: float | None = 0.5
    minimum_region_characters: int = 3
    small_region_height: float = 12.0
    contrast_range: float = 25.0
    symbol_fraction: float = 0.35
    symbol_minimum_characters: int = 8
    group_overlap: float | None = 0.5


# Development-set selection; not a production setting or a quality guarantee.
BALANCED_EXPERIMENTAL_PARAMETERS = ExtendedParameters(regional_confidence=None)


def _box(region):
    polygon = region.get("input_polygon") or region.get("polygon")
    if not polygon:
        return None
    try:
        xs, ys = zip(*polygon, strict=True)
        bounds = (min(xs), min(ys), max(xs), max(ys))
        if not all(math.isfinite(float(v)) for v in bounds):
            return None
        return bounds if bounds[2] > bounds[0] and bounds[3] > bounds[1] else None
    except (TypeError, ValueError):
        return None


def additional_evidence(text, regions, groups, image, params=ExtendedParameters()):
    """Yield independent hypotheses, including explicit missing capabilities."""
    eligible = [
        r
        for r in regions
        if len(str(r.get("text", "")).strip()) >= params.minimum_region_characters
    ]
    scores = [
        float(r["confidence"])
        for r in eligible
        if isinstance(r.get("confidence"), (int, float))
        and not isinstance(r.get("confidence"), bool)
        and 0 <= r["confidence"] <= 1
    ]
    if params.regional_confidence is not None:
        low = sum(score < params.regional_confidence for score in scores)
        yield Signal(
            "low_region_confidence",
            "recognition",
            3,
            "triggered" if low else "clear" if scores else "unavailable",
            {
                "low_regions": low,
                "scored_regions": len(scores),
                "threshold": params.regional_confidence,
            },
        )

    boxes = [box for r in eligible if (box := _box(r)) is not None]
    small = sum(box[3] - box[1] < params.small_region_height for box in boxes)
    yield Signal(
        "small_text",
        "geometry",
        3,
        "triggered" if small else "clear" if boxes else "unavailable",
        {
            "small_regions": small,
            "measured_regions": len(boxes),
            "height_below_pixels": params.small_region_height,
        },
    )

    chars = [c for c in text if not c.isspace()]
    symbols = sum(unicodedata.category(c).startswith(("P", "S")) for c in chars)
    enough = len(chars) >= params.symbol_minimum_characters
    fraction = symbols / len(chars) if chars else 0
    yield Signal(
        "unusual_symbols",
        "characters",
        3,
        "triggered"
        if enough and fraction >= params.symbol_fraction
        else "clear"
        if enough
        else "unavailable",
        {
            "symbols": symbols,
            "characters": len(chars),
            "fraction": fraction,
            "threshold": params.symbol_fraction,
        },
    )

    overlaps = []
    group_boxes = [
        g.get("box")
        for g in groups
        if isinstance(g.get("box"), (list, tuple)) and len(g["box"]) == 4
    ]
    for i, a in enumerate(group_boxes if params.group_overlap is not None else []):
        for j, b in enumerate(group_boxes[i + 1 :], i + 1):
            intersection = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(
                0, min(a[3], b[3]) - max(a[1], b[1])
            )
            smaller = min(
                max(0, a[2] - a[0]) * max(0, a[3] - a[1]),
                max(0, b[2] - b[0]) * max(0, b[3] - b[1]),
            )
            if smaller and intersection / smaller >= params.group_overlap:
                overlaps.append([i, j])
    if params.group_overlap is not None:
        yield Signal(
            "overlapping_groups",
            "layout",
            3,
            "triggered"
            if overlaps
            else "clear"
            if len(group_boxes) == len(groups) and group_boxes
            else "unavailable",
            {
                "overlaps": overlaps,
                "groups": len(group_boxes),
                "fraction_of_smaller": params.group_overlap,
            },
        )

    ranges = []
    if image is not None:
        gray = np.asarray(image.convert("L"))
        height, width = gray.shape
        for x1, y1, x2, y2 in boxes:
            crop = gray[
                max(0, math.floor(y1)) : min(height, math.ceil(y2)),
                max(0, math.floor(x1)) : min(width, math.ceil(x2)),
            ]
            if crop.size:
                lo, hi = np.percentile(crop, (5, 95))
                ranges.append(float(hi - lo))
    low_contrast = sum(value < params.contrast_range for value in ranges)
    yield Signal(
        "low_region_contrast",
        "image",
        3,
        "triggered" if low_contrast else "clear" if ranges else "unavailable",
        {
            "low_regions": low_contrast,
            "measured_regions": len(ranges),
            "range_below": params.contrast_range,
            "percentiles": [5, 95],
        },
    )


def route_extended(text, regions, groups, image=None, params=ExtendedParameters()):
    """Run the existing cascade with additional signals before the dictionary."""
    started = time.perf_counter()
    baseline = evidence(text, regions, groups, Parameters())
    observations = []
    for _ in range(3):
        signal = next(baseline)
        observations.append(signal)
        if signal.state == "triggered":
            break
    else:
        for signal in additional_evidence(text, regions, groups, image, params):
            observations.append(signal)
            if signal.state == "triggered":
                break
        else:
            observations.append(next(baseline))
    triggered = [s.name for s in observations if s.state == "triggered"]
    unavailable = [s.name for s in observations if s.state == "unavailable"]
    return {
        "route": "inspect"
        if triggered
        else "unresolved"
        if unavailable
        else "no_signal",
        "signals": [asdict(s) for s in observations],
        "unavailable": unavailable,
        "elapsed_seconds": time.perf_counter() - started,
    }
