"""Probe line split where separate aligned continuation lines support a gutter."""

from vipi.ocr.merge import bounds, line_candidates, rectangle, reading_rows
from ._layout_rules import pregroup, order_units
from ._layout_footer import reorder
import cv2


def split_lines(step, units):
    originals = line_candidates([step])
    result = []
    for unit in units:
        if unit["type"] != "native_line":
            result.append(unit)
            continue
        index = unit["source_indices"][0]
        line = originals[index]
        words = line["words"]
        top = bounds(line["input_polygon"])
        if len(words) < 2 or "".join(
            "".join(w["text"].split()) for w in words
        ) != "".join(line["text"].split()):
            result.append(unit)
            continue
        eligible = []
        for i, other in enumerate(originals):
            if i == index:
                continue
            b = bounds(other["input_polygon"])
            if (
                b[1] > top[1]
                and b[1] < top[3]
                and (b[1] + b[3]) > (top[1] + top[3])
                and b[0] >= top[0]
                and b[2] <= top[2]
            ):
                eligible.append(other)
        rows = reading_rows(eligible)
        cuts = []
        for row in rows:
            for left, right in zip(row, row[1:]):
                a, b = bounds(left["input_polygon"]), bounds(right["input_polygon"])
                if a[2] < b[0]:
                    cut = (a[2] + b[0]) / 2
                    if all(
                        not bounds(w["input_polygon"])[0]
                        < cut
                        < bounds(w["input_polygon"])[2]
                        for w in words
                    ):
                        cuts.append(cut)
        if not cuts:
            result.append(unit)
            continue
        cuts = sorted(set(cuts))
        chunks = []
        for w in words:
            box = bounds(w["input_polygon"])
            k = sum(cut <= (box[0] + box[2]) / 2 for cut in cuts)
            if not chunks or chunks[-1][0] != k:
                chunks.append((k, []))
            chunks[-1][1].append(w)
        for _, chunk in chunks:
            result.append(
                {
                    "text": " ".join(w["text"] for w in chunk),
                    "box": list(bounds(rectangle(w["input_polygon"] for w in chunk))),
                    "type": "native_line_fragment",
                    "source_indices": [index],
                }
            )
        assert "".join(
            "".join(w["text"].split()) for _, chunk in chunks for w in chunk
        ) == "".join(line["text"].split())
    return result


def propose(step, image_path):
    image = image_path if hasattr(image_path, "shape") else cv2.imread(str(image_path))
    if image is None or image.shape[:2] != (step["height"], step["width"]):
        raise ValueError("Input mismatch")
    units, _ = pregroup(step, image)
    return reorder(order_units(split_lines(step, units), step["width"], step["height"]))
