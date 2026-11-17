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


def build_evidence(result, *, run_id=None, complete=True, image=None):
    # Detection consumes only the final OCR outcome, never individual variants.
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
    return {
        "run_id": run_id,
        "ocr_model": result.get("model"),
        "ocr_complete": complete,
        "scope": "final_ocr",
        "readings": values,
        "input_hash": digest(values),
        "image_hash": hashlib.sha256(image).hexdigest() if image else None,
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
