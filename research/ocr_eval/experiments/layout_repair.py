"""Build an alternative grouping from native OCR lines for visual review."""

from collections import Counter

from vipi.ocr.merge import bounds, line_candidates, reading_rows


def native_line_layout(step, original_text):
    """Preserve OCR characters and native line membership without references.

    Return no candidate if the native engine did not supply line membership or
    if the alternative would add or remove non-whitespace characters.
    """
    regions = step.get("regions", [])
    if not regions or any(r.get("line_id") is None for r in regions):
        return None
    lines = line_candidates([step])
    ordered = [line for row in reading_rows(lines) for line in row]
    groups = []
    for line in ordered:
        groups.append(
            {
                "text": line["text"],
                "box": list(bounds(line["input_polygon"])),
                "input_polygon": line["input_polygon"],
                "polygon": line["polygon"],
                "type": "native_line",
            }
        )
    text = "\n".join(g["text"] for g in groups)
    if Counter(c for c in text if not c.isspace()) != Counter(
        c for c in original_text if not c.isspace()
    ):
        return None
    return {"text": text, "groups": groups}
