"""Freeze exact readings and provenance; chunk without silently dropping text."""

import hashlib
import json
import re

API_TEXT_BYTES = 16000
CHUNK_OVERLAP = 256
# Sentence windows for local decision models (ADR 0077): long text dilutes an
# injection, so it is also checked in windows of whole sentences or lines.
WINDOW_WORDS = 80
WINDOW_STRIDE_WORDS = 40
UNIT_BREAK = re.compile(r"(?<=[.!?])\s+|\n+")


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()


def reading_scores(answers, readings):
    """Highest completed score per reading; the OCR reading is reported as `ocr`.

    ``readings`` names the reading kinds to report, for example
    ``("ocr", "svg_source")``.
    """
    scores = {}
    for answer in answers:
        score = answer.get("probability")
        if answer.get("status") != "completed" or score is None:
            continue
        for source in answer.get("source_ids", ()):
            reading = "ocr" if source == "assembled" else source
            if reading in readings:
                scores[reading] = max(score, scores.get(reading, score))
    return scores


def build_evidence(
    result,
    *,
    run_id=None,
    complete=True,
    image=None,
    source_text=None,
    metadata_text=None,
    barcode_text=None,
    openstego_texts=None,
    view_texts=None,
    incomplete=(),
):
    """Freeze final OCR text and any SVG, metadata, barcode or OpenStego readings.

    ``view_texts`` maps reading kinds such as ``ocr_black`` to the final OCR
    text of a transparency view (ADR 0085).

    Detection consumes only the final OCR outcome, never individual variants.
    ``incomplete`` lists reasons why a scan cannot be declared clean.
    """
    text = result.get("text", "") if complete else ""
    if not isinstance(text, str):
        raise ValueError("Saved OCR text must be a string.")
    values = []
    if text.strip():
        values.append(
            {
                "id": digest(text),
                "text": text,
                "sources": [
                    {
                        "kind": "assembled",
                        "id": "assembled",
                        "assembly_version": result.get("assembly_version"),
                    }
                ],
            }
        )
    for kind, extra in (
        *(view_texts or {}).items(),
        ("svg_source", source_text),
        ("image_metadata", metadata_text),
        ("barcode", barcode_text),
        *(openstego_texts or {}).items(),
    ):
        if extra is None or not extra.strip():
            continue
        source = {"kind": kind, "id": kind}
        same = [value for value in values if value["id"] == digest(extra)]
        if same:
            same[0]["sources"].append(source)
        else:
            values.append({"id": digest(extra), "text": extra, "sources": [source]})
    scope = "final_ocr"
    if view_texts is not None:
        scope += "_and_transparency_views"
    if source_text is not None:
        scope += "_and_svg_source"
    if metadata_text is not None:
        scope += "_and_image_metadata"
    if barcode_text is not None:
        scope += "_and_barcodes"
    for kind in openstego_texts or ():
        scope += f"_and_{kind}"
    return {
        "run_id": run_id,
        "ocr_model": result.get("model"),
        "ocr_complete": complete,
        "scope": scope,
        "readings": values,
        "input_hash": digest(values),
        "image_hash": hashlib.sha256(image).hexdigest() if image else None,
        **({"incomplete": list(incomplete)} if incomplete else {}),
    }


def chunks(text, *, limit=API_TEXT_BYTES, overlap=CHUNK_OVERLAP):
    """Bound JSON-encoded UTF-8 bytes, a conservative API token upper bound."""
    if limit < 8 or overlap < 0:
        raise ValueError("Invalid chunk limits.")
    start = 0
    while start < len(text):
        low, high = start + 1, len(text)
        while low < high:
            middle = (low + high + 1) // 2
            if (
                len(json.dumps(text[start:middle], ensure_ascii=False).encode())
                <= limit
            ):
                low = middle
            else:
                high = middle - 1
        end = low
        yield {
            "text": text[start:end],
            "start": start,
            "end": end,
            "partial_context": start != 0 or end != len(text),
            "kind": "text",
        }
        if end == len(text):
            break
        start = end - min(overlap, (end - start) // 4)


def units(text):
    """Character spans of the sentences or lines of ``text``."""
    spans, start = [], 0
    for separator in [*UNIT_BREAK.finditer(text), None]:
        end = separator.start() if separator else len(text)
        piece = text[start:end]
        if piece.strip():
            left = start + len(piece) - len(piece.lstrip())
            spans.append((left, start + len(piece.rstrip())))
        if separator:
            start = separator.end()
    return spans


def windows(text, *, words=WINDOW_WORDS, stride=WINDOW_STRIDE_WORDS):
    """Windows of whole units with at most ``words`` words, one about every
    ``stride`` words. Text that fits into one window gets none: the whole-text
    check covers it. A single unit longer than ``words`` is one window."""
    spans = units(text)
    counts = [len(text[a:b].split()) for a, b in spans]
    if sum(counts) <= words:
        return
    offsets = [sum(counts[:index]) for index in range(len(counts) + 1)]
    first = 0
    while True:
        last = first + 1
        while last < len(spans) and offsets[last + 1] - offsets[first] <= words:
            last += 1
        yield {
            "text": text[spans[first][0] : spans[last - 1][1]],
            "start": spans[first][0],
            "end": spans[last - 1][1],
            "partial_context": True,
            "kind": "window",
        }
        if last == len(spans):
            return
        following = next(
            index
            for index in range(first + 1, len(spans) + 1)
            if index == len(spans) or offsets[index] - offsets[first] >= stride
        )
        # Never start beyond the current window, so no unit is skipped.
        first = min(following, last)
