"""Retain OCR evidence when applying spatially supported letter insertions."""

from collections import Counter
from functools import cache
import math
import re

from vipi.ocr.merge import bounds

from .reading_edits import apply_approved


def retained_confident_tokens(incumbent_regions, candidate_text, confidence=0.9):
    """Return confident incumbent OCR tokens missing from a candidate.

    This check uses no reference text and can reject a genuine correction when
    the incumbent OCR is confidently wrong.
    """
    old = Counter()
    for region in incumbent_regions:
        score = region.get("confidence")
        if (
            isinstance(score, (int, float))
            and not isinstance(score, bool)
            and confidence <= score <= 1
        ):
            old.update(re.findall(r"\w+", region.get("text", "").casefold()))
    if not old:
        raise ValueError("No confident OCR tokens available for retention check")
    new = Counter(re.findall(r"\w+", candidate_text.casefold()))
    return list((old - new).elements())


@cache
def _word_frequency(word):
    from wordfreq import available_languages, zipf_frequency

    values = []
    for language in available_languages():
        try:
            values.append(zipf_frequency(word, language))
        except (ImportError, ModuleNotFoundError):
            continue
    return max(values, default=0)


def _confidence(region):
    value = region.get("confidence")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value if math.isfinite(value) and 0 <= value <= 1 else None


def _overlap(first, second):
    if not first.get("input_polygon") or not second.get("input_polygon"):
        return 0
    a, b = bounds(first["input_polygon"]), bounds(second["input_polygon"])
    area = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
    if area <= 0:
        return 0
    return (
        max(0, min(a[2], b[2]) - max(a[0], b[0]))
        * max(0, min(a[3], b[3]) - max(a[1], b[1]))
        / area
    )


def insertion_retention(
    incumbent_regions,
    candidate_regions,
    candidate_text,
    *,
    word_frequency=_word_frequency,
):
    """Retain confident tokens, allowing only higher-confidence letter additions.

    This exploratory guard relaxes exact retention for alphabetic OCR words of
    at least three characters at the same location. Every incumbent character
    must remain in order, and the new spelling must have higher multilingual
    word frequency. Short anchors, numbers, code and substitutions retain the
    existing exact-token guard. These are exploratory development heuristics.
    """
    missing = Counter(retained_confident_tokens(incumbent_regions, candidate_text))
    corrections, used = [], set()
    for old in incumbent_regions:
        old_text = old.get("text", "").casefold()
        old_score = _confidence(old)
        if (
            not missing[old_text]
            or len(old_text) < 3
            or not old_text.isalpha()
            or old_score is None
            or old_score < 0.9
        ):
            continue
        matches = []
        for index, new in enumerate(candidate_regions):
            new_text = new.get("text", "").casefold()
            new_score = _confidence(new)
            if (
                index in used
                or not new_text.isalpha()
                or len(new_text) <= len(old_text)
                or new_score is None
                or new_score <= old_score
                or _overlap(old, new) < 0.5
            ):
                continue
            letters = iter(new_text)
            if all(
                any(letter == character for letter in letters) for character in old_text
            ):
                old_frequency = word_frequency(old_text)
                new_frequency = word_frequency(new_text)
                if new_frequency > old_frequency:
                    matches.append(
                        (new_score, index, new, old_frequency, new_frequency)
                    )
        if not matches:
            continue
        _, index, new, old_frequency, new_frequency = max(
            matches, key=lambda match: match[0]
        )
        used.add(index)
        missing[old_text] -= 1
        corrections.append(
            {
                "old": old["text"],
                "new": new["text"],
                "old_confidence": old_score,
                "new_confidence": new["confidence"],
                "old_frequency": old_frequency,
                "new_frequency": new_frequency,
                "input_polygon": old["input_polygon"],
            }
        )
    return {"missing": list(missing.elements()), "corrections": corrections}


def repair_resolution_reading(
    groups,
    incumbent_regions,
    candidate_regions,
    candidate_text,
    *,
    word_frequency=_word_frequency,
):
    """Apply supported insertions locally while preserving the rest of the page."""
    retained = insertion_retention(
        incumbent_regions,
        candidate_regions,
        candidate_text,
        word_frequency=word_frequency,
    )
    changes = [
        {**correction, "box": list(bounds(correction["input_polygon"]))}
        for correction in retained["corrections"]
    ]
    source_groups = [
        {**group, "box": list(bounds(group["input_polygon"]))}
        if group.get("input_polygon")
        else dict(group)
        for group in groups
    ]
    allowed = bool(changes) and not retained["missing"]
    result = apply_approved(source_groups, changes, [allowed] * len(changes))
    return {**result, "retention": retained}
