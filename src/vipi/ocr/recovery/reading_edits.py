"""Apply spatially supported OCR corrections without changing other groups."""

from copy import deepcopy
import re


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
