"""Freeze exact readings and provenance; chunk without silently dropping text."""

import hashlib
import json

API_TEXT_BYTES = 16000
CHUNK_OVERLAP = 256


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
        }
        if end == len(text):
            break
        start = end - min(overlap, (end - start) // 4)
