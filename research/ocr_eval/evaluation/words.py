"""One-to-one reference-word coverage with explicit OCR spelling tolerance."""

import re
import unicodedata
from collections import Counter

WORD_ERROR_RATE = 0.20


def words(text):
    """Whitespace-delimited words, retaining their literal attached symbols."""
    return [word for word in text.split() if re.search(r"\w", word)]


def normalized(word):
    return re.sub(r"[^\w]", "", unicodedata.normalize("NFKC", word).casefold())


def edit_budget(word):
    # A one-character token has no smaller, still identifiable spelling.
    return max(1, int(len(word) * WORD_ERROR_RATE)) if len(word) > 1 else 0


def bounded_distance(first, second, budget):
    """Levenshtein distance inside the accepted edit band, or None."""
    if abs(len(first) - len(second)) > budget:
        return None
    if first == second:
        return 0
    # Character counts give a cheap lower bound before aligning long strings
    # against unrelated background text. One edit fixes at most one excess
    # character of either side.
    differences = Counter(first)
    differences.subtract(second)
    if (
        max(
            sum(value for value in differences.values() if value > 0),
            -sum(value for value in differences.values() if value < 0),
        )
        > budget
    ):
        return None
    previous = {j: j for j in range(min(len(second), budget) + 1)}
    beyond = budget + 1
    for i, left in enumerate(first, 1):
        current = {0: i} if i <= budget else {}
        for j in range(max(1, i - budget), min(len(second), i + budget) + 1):
            current[j] = min(
                current.get(j - 1, beyond) + 1,
                previous.get(j, beyond) + 1,
                previous.get(j - 1, beyond) + (left != second[j - 1]),
            )
        if not current or min(current.values()) > budget:
            return None
        previous = current
    result = previous.get(len(second), beyond)
    return result if result <= budget else None


def word_distance(expected, observed, *, exact=False, cache=None):
    if exact:
        return 0 if expected == observed else None
    expected, observed = normalized(expected), normalized(observed)
    key = expected, observed
    if cache is not None and key in cache:
        return cache[key]
    result = bounded_distance(expected, observed, edit_budget(expected))
    if cache is not None:
        cache[key] = result
    return result


def word_matches(expected, observed, *, exact=False, cache=None):
    """Ordered word alignment, allowing a word split into OCR fragments.

    Each observation is consumed at most once. Extra OCR words are allowed.
    Prefer more covered words, then literal matches, then fewer spelling edits.
    Store reference positions as bitsets so memory grows with OCR word count,
    rather than the product of both sequence lengths.
    """
    previous = [(0, 0, 0, 0)] * (len(observed) + 1)
    for index, target in enumerate(expected):
        current = previous.copy()
        value = target if exact else normalized(target)
        budget = 0 if exact else edit_budget(value)
        for start in range(len(observed)):
            if current[start][:3] > current[start + 1][:3]:
                current[start + 1] = current[start]
            candidate = ""
            for end in range(start, len(observed)):
                candidate += observed[end]
                length = len(candidate if exact else normalized(candidate))
                if length > len(value) + budget:
                    break
                if length < len(value) - budget:
                    continue
                distance = word_distance(target, candidate, exact=exact, cache=cache)
                if distance is None:
                    continue
                count, literal, edits, positions = previous[start]
                proposal = (
                    count + 1,
                    literal + int(target == candidate),
                    edits - distance,
                    positions | (1 << index),
                )
                if proposal[:3] > current[end + 1][:3]:
                    current[end + 1] = proposal
        previous = current
    positions = previous[-1][3]
    return {i for i in range(len(expected)) if positions & (1 << i)}
