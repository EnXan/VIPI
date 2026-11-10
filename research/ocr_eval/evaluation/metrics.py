"""Tolerant reference-word coverage and separate literal word fidelity."""

import re
import unicodedata
from collections import Counter

from vipi.ocr.merge import bounds
from .words import WORD_ERROR_RATE, word_distance, word_matches, words

EVALUATION_VERSION = 4


def evaluation_policy():
    return {
        "version": EVALUATION_VERSION,
        "primary": "final_word_coverage",
        "words": "whitespace-delimited units containing Unicode word characters",
        "word_error_rate": WORD_ERROR_RATE,
        "short_words": "one edit for words of two or more characters; single characters exact",
        "normalization": "NFKC, casefold and punctuation removal for tolerant coverage only",
        "exact": "literal case-sensitive words including attached symbols; standalone punctuation excluded",
        "word_splits": "adjacent OCR fragments may cover one reference word",
        "region_order": (
            "word order is preserved within each reference region; "
            "order between regions is ignored"
        ),
        "region_grouping": (
            "observations overlapping multiple independent reference regions "
            "are reported as conflicts and prevent passing"
        ),
        "reference_scope": "annotated reference only, not necessarily all visible image text",
    }


def tokens(text):
    return re.findall(r"\w+|[^\w\s]", unicodedata.normalize("NFKC", text).casefold())


def box_overlap(a, b):
    intersection = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(
        0, min(a[3], b[3]) - max(a[1], b[1])
    )
    area = min(
        max(0, a[2] - a[0]) * max(0, a[3] - a[1]),
        max(0, b[2] - b[0]) * max(0, b[3] - b[1]),
    )
    return intersection / area if area else 0


def final_observations(regions, variants):
    """Retain selected native word positions rather than a merged line's broad box."""
    steps = {step["id"]: step for step in variants}
    observations = []
    for region in regions:
        native_words = region.get("words")
        if native_words and "".join(tokens(region["text"])) == "".join(
            tokens(" ".join(word["text"] for word in native_words))
        ):
            observations.extend(native_words)
            continue
        selected = steps.get(region.get("selected_step_id"))
        anchor = next(
            (
                item
                for item in region.get("evidence", [])
                if item["step_id"] == region.get("selected_step_id")
            ),
            region,
        )
        if selected is None:
            observations.append(region)
            continue
        candidates = [
            word
            for word in selected["regions"]
            if box_overlap(
                bounds(word["input_polygon"]), bounds(anchor["input_polygon"])
            )
            >= 0.5
        ]
        candidates += region.get("additions", [])
        # Older saved results lack selected native words. A compact raw line
        # may still be exactly reproduced by its native word boxes.
        if "".join(tokens(region["text"])) == "".join(
            tokens(" ".join(candidate["text"] for candidate in candidates))
        ):
            observations.extend(candidates)
            continue
        remaining = Counter(tokens(region["text"]))
        for candidate in candidates:
            included = []
            for token in tokens(candidate["text"]):
                if remaining[token]:
                    included.append(token)
                    remaining[token] -= 1
            if included:
                observations.append(
                    {
                        "text": " ".join(included),
                        "input_polygon": candidate["input_polygon"],
                    }
                )
    return observations


def region_group_conflicts(reference, observations):
    if not reference.get("regions_are_independent"):
        return []
    reference_boxes = [
        bounds(region["input_polygon"]) for region in reference["regions"]
    ]
    conflicts = []
    for index, observation in enumerate(observations):
        polygon = observation.get("input_polygon")
        if not polygon:
            continue
        matched_regions = [
            region_index
            for region_index, box in enumerate(reference_boxes)
            if box_overlap(bounds(polygon), box) >= 0.5
        ]
        if len(matched_regions) > 1:
            conflicts.append(
                {
                    "observation_index": index,
                    "reference_region_indexes": matched_regions,
                }
            )
    return conflicts


def region_matches(reference, observations, *, exact=False, cache=None):
    """One-to-one token matching in overlapping input-coordinate word regions."""
    tokenize = words
    expected = [
        (token, bounds(region["input_polygon"]))
        for region in reference["regions"]
        for token in tokenize(region["text"])
    ]
    observed = [
        (token, bounds(region["input_polygon"]))
        for region in observations
        if region.get("input_polygon")
        for token in tokenize(region["text"])
    ]

    edges = []
    ordered_positions, offset = set(), 0
    for region in reference["regions"]:
        unit = tokenize(region["text"])
        local = [
            token
            for token, box in observed
            if box_overlap(bounds(region["input_polygon"]), box) >= 0.5
        ]
        matched = word_matches(unit, local, exact=exact, cache=cache)
        ordered_positions.update(offset + index for index in matched)
        offset += len(unit)
    for index, (token, box) in enumerate(expected):
        scores = [
            (box_overlap(box, candidate), j)
            for j, (text, candidate) in enumerate(observed)
            if word_distance(token, text, exact=exact, cache=cache) is not None
        ]
        edges.append(
            [j for score, j in sorted(scores, reverse=True) if score >= 0.5]
            if index in ordered_positions
            else []
        )
    owners = {}

    def assign(index, visited):
        for candidate in edges[index]:
            if candidate in visited:
                continue
            visited.add(candidate)
            if candidate not in owners or assign(owners[candidate], visited):
                owners[candidate] = index
                return True
        return False

    for index in range(len(expected)):
        assign(index, set())
    return [token for token, _ in expected], set(owners.values())


def score(expected, matched):
    return {
        "valid": bool(expected) and len(matched) == len(expected),
        "matched": len(matched),
        "total": len(expected),
        "coverage": len(matched) / len(expected) if expected else 0,
        "missing": [
            token for index, token in enumerate(expected) if index not in matched
        ],
    }


def compare_words(reference, text, regions, *, cache=None):
    if reference["reading_order_known"]:
        expected, observed = words(reference["text"]), words(text)
        matched = word_matches(expected, observed, cache=cache)
        exact = word_matches(expected, observed, exact=True)
    else:
        if not reference["regions"]:
            raise ValueError("Unordered references require annotated word regions.")
        expected, matched = region_matches(reference, regions, cache=cache)
        _, exact = region_matches(reference, regions, exact=True)
    conflicts = region_group_conflicts(reference, regions)
    result = score(expected, matched)
    result["exact"] = score(expected, exact)
    if conflicts:
        result["valid"] = False
        result["exact"]["valid"] = False
        result["group_conflicts"] = conflicts
    return result, expected, matched
