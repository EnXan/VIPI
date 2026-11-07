"""Weak local evidence for OCR disagreement on long code-like text."""

from collections import Counter
import re

from vipi.ocr.merge import bounds


def _box(group):
    try:
        return bounds(group["input_polygon"])
    except (KeyError, TypeError, ValueError):
        return None


def _overlap(a, b):
    intersection = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(
        0, min(a[3], b[3]) - max(a[1], b[1])
    )
    smaller = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
    return intersection / smaller if smaller > 0 else 0


def code_disagreements(primary_groups, alternate_groups):
    """Report overlapping readings with different long encoded-like tokens.

    The minimum run length is an exploratory signal to reduce ordinary-word
    noise; it neither limits input nor proves that a string is an encoded
    payload, invalid, or malicious. No reference labels are used.
    """
    if any(_box(g) is None for g in primary_groups):
        raise ValueError("Primary group geometry unavailable")
    if any(_box(g) is None for g in alternate_groups):
        raise ValueError("Alternate group geometry unavailable")
    pattern = re.compile(r"[A-Za-z0-9+/_=-]{24,}")
    changes = []
    for i, old in enumerate(primary_groups):
        a = _box(old)
        if a is None:
            continue
        old_tokens = Counter(pattern.findall(old.get("text", "")))
        for j, new in enumerate(alternate_groups):
            b = _box(new)
            if b is None or _overlap(a, b) < 0.5:
                continue
            new_tokens = Counter(pattern.findall(new.get("text", "")))
            if (old_tokens or new_tokens) and old_tokens != new_tokens:
                changes.append(
                    {
                        "primary_group": i,
                        "alternate_group": j,
                        "box": list(a),
                        "primary_tokens": list(old_tokens.elements()),
                        "alternate_tokens": list(new_tokens.elements()),
                    }
                )
    return changes
