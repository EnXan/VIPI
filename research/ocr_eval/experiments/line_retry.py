"""Research retry for OCR lines containing an isolated ambiguous lowercase l."""

from copy import deepcopy
import math
import re

from PIL import Image

from vipi.ocr.merge import bounds, line_candidates


def _intersection(a, b):
    return max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(
        0, min(a[3], b[3]) - max(a[1], b[1])
    )


def retry_ambiguous_lines(raster, step, groups, engine):
    """Read each eligible whole line once; propose changes only at isolated l.

    The trigger is an experimental script-specific hint. Reference text is
    never inspected. The original reading is retained until independently
    reviewed. Coordinates in step.polygon belong to the selected raster.
    """
    proposals, attempts = [], []
    for line in line_candidates([step]):
        targets = [w for w in line["words"] if w["text"] == "l"]
        if not targets or len(line["words"]) < 2:
            continue
        old = line["text"]
        positions = list(re.finditer(r"(?<!\w)l(?!\w)", old))
        indices = [i for i, g in enumerate(groups) if g["text"].count(old) == 1]
        if len(positions) != len(targets) or len(indices) != 1:
            attempts.append({"line": old, "status": "unmapped"})
            continue
        box = bounds(line["polygon"])
        padding = max(1, box[3] - box[1])
        left, top = (
            max(0, math.floor(box[0] - padding)),
            max(0, math.floor(box[1] - padding)),
        )
        right, bottom = (
            min(raster.width, math.ceil(box[2] + padding)),
            min(raster.height, math.ceil(box[3] + padding)),
        )
        if right <= left or bottom <= top:
            attempts.append({"line": old, "status": "invalid_crop"})
            continue
        crop = raster.crop((left, top, right, bottom))
        crop = crop.resize((crop.width * 2, crop.height * 2), Image.Resampling.LANCZOS)
        observed = engine.recognize(crop)
        replacements = []
        for target, pos in zip(targets, positions, strict=True):
            original_box = bounds(target["polygon"])
            scaled_box = tuple(
                2 * (value - offset)
                for value, offset in zip(
                    original_box, (left, top, left, top), strict=True
                )
            )
            found = []
            for candidate in observed.get("regions", []):
                text = candidate.get("text", "").strip()
                if (
                    not re.fullmatch(r"[Il1]+", text)
                    or text == "l"
                    or not candidate.get("polygon")
                ):
                    continue
                candidate_box = bounds(candidate["polygon"])
                size = min(
                    (candidate_box[2] - candidate_box[0])
                    * (candidate_box[3] - candidate_box[1]),
                    (scaled_box[2] - scaled_box[0]) * (scaled_box[3] - scaled_box[1]),
                )
                if size > 0 and _intersection(scaled_box, candidate_box) >= 0.5 * size:
                    found.append(text)
            if len(found) == 1:
                replacements.append((pos.start(), pos.end(), found[0]))
        attempts.append(
            {"line": old, "status": "recognized", "observed": observed["text"]}
        )
        if not replacements:
            continue
        new = old
        for start, end, text in reversed(replacements):
            new = new[:start] + text + new[end:]
        proposals.append(
            {
                "old": old,
                "new": new,
                "box": list(bounds(line["input_polygon"])),
                "group_index": indices[0],
            }
        )
    return {"proposals": proposals, "attempts": attempts}


def apply_line_choices(groups, proposals, approved):
    """Replace the exact line only after independent approval."""
    updated = deepcopy(groups)
    applied = []
    for proposal, accept in zip(proposals, approved, strict=True):
        if not accept:
            continue
        group = updated[proposal["group_index"]]
        if group["text"].count(proposal["old"]) != 1:
            continue
        group["text"] = group["text"].replace(proposal["old"], proposal["new"], 1)
        applied.append(proposal)
    return {
        "text": "\n".join(g["text"] for g in updated),
        "regions": updated,
        "changes": applied,
    }
