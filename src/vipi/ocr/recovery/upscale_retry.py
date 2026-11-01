"""Retain confident native OCR tokens when reviewing candidate readings."""

from collections import Counter
import re


def retained_confident_tokens(incumbent_regions, candidate_text, confidence=0.9):
    """List confident native OCR tokens not present in candidate transcription.

    This conservative experimental check uses no reference text. It can reject
    genuine corrections when the incumbent is confidently wrong.
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
