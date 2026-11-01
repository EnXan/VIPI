"""Experimental ruled-row pregrouping before pdfminer hierarchy construction."""

from collections import Counter
import statistics
import cv2
import numpy as np
from pdfminer.layout import (
    LAParams,
    LTPage,
    LTTextBoxHorizontal,
    LTTextLineHorizontal,
    LTAnno,
    LTTextGroup,
    LTContainer,
)
from vipi.ocr.merge import bounds, line_candidates, reading_rows, rectangle


def horizontal_rules(image, text_height):
    """Find low-contrast long rules at the observed OCR text scale.

    The morphology length (8 text heights) rejects ordinary letter strokes;
    a vertical Sobel threshold of 8 retains faint UI rules. A 3-pixel vertical
    closing connects the two edges of a thin rule.
    These are experimental pixel heuristics, not OCR/model requirements.
    """
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    gradient = np.abs(cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3))
    mask = (gradient >= 8).astype(np.uint8) * 255
    kernel = cv2.getStructuringElement(
        cv2.MORPH_RECT, (max(1, round(8 * text_height)), 1)
    )
    horizontal = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    horizontal = cv2.morphologyEx(
        horizontal, cv2.MORPH_CLOSE, np.ones((3, 1), np.uint8)
    )
    contours, _ = cv2.findContours(
        horizontal, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    rules = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if h < text_height:
            rules.append([x, y, x + w, y + h])
    return rules


def rule_families(rules, text_height):
    """Repeated separators with almost equal spans support a ruled-row region.

    At least two distinct rule heights distinguish rows from a single heading
    underline. 90% mutual horizontal overlap tolerates small endpoint variations.
    """
    groups = []
    for rule in sorted(rules, key=lambda r: r[1]):
        family = next(
            (
                g
                for g in groups
                if all(
                    max(0, min(rule[2], other[2]) - max(rule[0], other[0]))
                    >= 0.9 * max(rule[2] - rule[0], other[2] - other[0])
                    for other in g
                )
            ),
            None,
        )
        if family is None:
            groups.append([rule])
        else:
            family.append(rule)
    return [
        g for g in groups if max(r[1] for r in g) - min(r[1] for r in g) > text_height
    ]


def pregroup(step, image):
    lines = line_candidates([step])
    if not lines:
        return [], []
    text_height = statistics.median(
        bounds(line["input_polygon"])[3] - bounds(line["input_polygon"])[1]
        for line in lines
    )
    families = rule_families(horizontal_rules(image, text_height), text_height)
    source = {id(line): i for i, line in enumerate(lines)}
    used = set()
    units = []
    for row in reading_rows(lines):
        for family in families:
            left = max(r[0] for r in family)
            right = min(r[2] for r in family)
            selected = [
                line
                for line in row
                if source[id(line)] not in used
                and bounds(line["input_polygon"])[0] >= left - text_height
                and bounds(line["input_polygon"])[2] <= right + text_height
            ]
            if len(selected) < 2:
                continue
            box = bounds(rectangle(line["input_polygon"] for line in selected))
            center = (box[1] + box[3]) / 2
            nearby = any(
                abs((r[1] + r[3]) / 2 - center) <= 2 * text_height
                and (r[3] <= box[1] or r[1] >= box[3])
                for r in family
            )
            if not nearby:
                continue
            indices = [source[id(line)] for line in selected]
            unit = {
                "text": " | ".join(line["text"] for line in selected),
                "box": list(box),
                "type": "ruled_row",
                "source_indices": indices,
            }
            used.update(indices)
            units.append(unit)
    units.extend(
        {
            "text": line["text"],
            "box": list(bounds(line["input_polygon"])),
            "type": "native_line",
            "source_indices": [i],
        }
        for i, line in enumerate(lines)
        if i not in used
    )
    assert Counter(i for g in units for i in g["source_indices"]) == Counter(
        range(len(lines))
    )
    return units, families


def order_units(units, width, height):
    if not units:
        return []
    boxes = []
    for i, unit in enumerate(units):
        left, top, right, bottom = unit["box"]
        line = LTTextLineHorizontal(0.1)
        LTContainer.add(line, LTAnno(unit["text"]))
        line.set_bbox((left, height - bottom, right, height - top))
        box = LTTextBoxHorizontal()
        box.add(line)
        box.source_index = i
        boxes.append(box)
    params = LAParams()
    roots = LTPage(1, (0, 0, width, height)).group_textboxes(params, boxes)
    for root in roots:
        root.analyze(params)
    order = []

    def visit(node):
        if isinstance(node, LTTextGroup):
            for child in node:
                visit(child)
        else:
            order.append(node.source_index)

    for root in roots:
        visit(root)
    assert sorted(order) == list(range(len(units)))
    return [units[i] for i in order]


def table_groups(step, image_path):
    image = cv2.imread(str(image_path))
    if image is None:
        raise ValueError(f"Cannot read image: {image_path}")
    if image.shape[:2] != (step["height"], step["width"]):
        raise ValueError("Image and saved OCR coordinates differ")
    units, families = pregroup(step, image)
    return order_units(units, step["width"], step["height"]), families
