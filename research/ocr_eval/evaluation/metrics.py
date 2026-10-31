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


EFFECT_LABELS = {
    "scaling": "Scaling",
    "rotation": "Rotation",
    "tiling": "Tiling",
    "grayscale": "Grayscale",
    "clahe": "CLAHE",
    "inverted": "Inversion",
    "threshold": "Threshold",
    "color-contrast": "Color contrast",
}


def tokens(text):
    return re.findall(r"\w+|[^\w\s]", unicodedata.normalize("NFKC", text).casefold())


def ordered_matches(expected, observed):
    """Exact LCS with bitsets; return reference positions, never penalize insertions."""
    masks = {}
    for index, token in enumerate(expected):
        masks[token] = masks.get(token, 0) | (1 << index)
    rows = [0]
    for token in observed:
        union = rows[-1] | masks.get(token, 0)
        rows.append(union & ~(union - ((rows[-1] << 1) | 1)))
    i, j, matched = len(expected) - 1, len(observed) - 1, set()
    while i >= 0 and j >= 0:
        if expected[i] == observed[j]:
            matched.add(i)
            i -= 1
            j -= 1
        elif (rows[j] & ((1 << (i + 1)) - 1)).bit_count() == (
            rows[j + 1] & ((1 << (i + 1)) - 1)
        ).bit_count():
            j -= 1
        else:
            i -= 1
    return matched


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


def region_matches(
    reference, observations, *, word_mode=False, exact=False, cache=None
):
    """One-to-one token matching in overlapping input-coordinate word regions."""
    tokenize = words if word_mode else tokens
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
        matched = (
            word_matches(unit, local, exact=exact, cache=cache)
            if word_mode
            else ordered_matches(unit, local)
        )
        ordered_positions.update(offset + index for index in matched)
        offset += len(unit)
    for index, (token, box) in enumerate(expected):
        scores = [
            (box_overlap(box, candidate), j)
            for j, (text, candidate) in enumerate(observed)
            if (
                word_distance(token, text, exact=exact, cache=cache) is not None
                if word_mode
                else text == token
            )
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


def compare(reference, text, regions):
    """Legacy normalized exact-token comparison for historical experiments."""
    if reference["reading_order_known"]:
        expected = tokens(reference["text"])
        matched = ordered_matches(expected, tokens(text))
    else:
        if not reference["regions"]:
            raise ValueError("Unordered references require annotated word regions.")
        expected, matched = region_matches(reference, regions)
    result = score(expected, matched)
    conflicts = region_group_conflicts(reference, regions)
    if conflicts:
        result["valid"] = False
        result["group_conflicts"] = conflicts
    return result, expected, matched


def compare_words(reference, text, regions, *, cache=None):
    if reference["reading_order_known"]:
        expected, observed = words(reference["text"]), words(text)
        matched = word_matches(expected, observed, cache=cache)
        exact = word_matches(expected, observed, exact=True)
    else:
        if not reference["regions"]:
            raise ValueError("Unordered references require annotated word regions.")
        expected, matched = region_matches(
            reference, regions, word_mode=True, cache=cache
        )
        _, exact = region_matches(reference, regions, word_mode=True, exact=True)
    conflicts = region_group_conflicts(reference, regions)
    result = score(expected, matched)
    result["exact"] = score(expected, exact)
    if conflicts:
        result["valid"] = False
        result["exact"]["valid"] = False
        result["group_conflicts"] = conflicts
    return result, expected, matched


def effect_summary(evaluations, variants):
    by_view = {(step["view_id"], step["filter"]): step for step in variants}
    original = next(step["view_id"] for step in variants if step["index"] == 1)
    effects = {
        key: {
            "id": key,
            "label": label,
            "comparisons": 0,
            "improved": 0,
            "unchanged": 0,
            "worse": 0,
            "recovered": 0,
            "delta_sum": 0.0,
        }
        for key, label in EFFECT_LABELS.items()
    }
    for step in variants:
        transform = step["transformation"]
        if step["filter"] != "unchanged":
            effect = step["filter"]
            baseline = by_view.get((step["view_id"], "unchanged"))
            if baseline is None:
                # Reduced profiles can contain a filtered view without its control.
                continue
        elif transform.get("crop"):
            effect, baseline = "tiling", by_view[(original, "unchanged")]
        elif transform.get("rotation"):
            effect, baseline = "rotation", by_view[(original, "unchanged")]
        elif step["view_id"] != original:
            effect, baseline = "scaling", by_view[(original, "unchanged")]
        else:
            continue
        current, before = evaluations[step["id"]], evaluations[baseline["id"]]
        delta = current["coverage"] - before["coverage"]
        item = effects[effect]
        item["comparisons"] += 1
        item["improved" if delta > 0 else "worse" if delta < 0 else "unchanged"] += 1
        item["recovered"] += int(current["valid"] and not before["valid"])
        item["delta_sum"] += delta
    return list(effects.values())


def evaluate(reference, text, regions, variants, *, include_effects=True):
    evaluations, all_matched, cache = {}, set(), {}
    for step in variants:
        result, expected, matched = compare_words(
            reference, step["text"], step["regions"], cache=cache
        )
        evaluations[step["id"]] = result
        all_matched.update(matched)
    final_regions = (
        regions
        if reference["reading_order_known"]
        else final_observations(regions, variants)
    )
    final, expected, final_matched = compare_words(
        reference, text, final_regions, cache=cache
    )
    best = max(
        variants, key=lambda step: (evaluations[step["id"]]["matched"], -step["index"])
    )
    best_score = evaluations[best["id"]]
    if reference["reading_order_known"]:
        detection = final if final["matched"] > best_score["matched"] else best_score
    else:
        detection = score(expected, all_matched | final_matched)
        # Geometry diagnostics may combine distinct locations across views.
        # Literal fidelity is measured on actual texts, not an invented union.
        detection["exact"] = max(
            [final["exact"], *(value["exact"] for value in evaluations.values())],
            key=lambda value: value["matched"],
        )
    return {
        "version": EVALUATION_VERSION,
        "reference": reference,
        "policy": evaluation_policy(),
        "method": "ordered_words"
        if reference["reading_order_known"]
        else "word_regions",
        "valid": final["valid"],
        "detection": detection,
        "final": final,
        "original": evaluations[variants[0]["id"]],
        "best_step_id": best["id"],
        "best_label": best["label"],
        "valid_step_ids": [
            step["id"] for step in variants if evaluations[step["id"]]["valid"]
        ],
        "steps": evaluations,
        "effects": effect_summary(evaluations, variants) if include_effects else [],
    }


def word_summary(items):
    completed = [item for item in items if item["state"] == "completed"]
    processed = [
        item
        for item in items
        if item["state"] == "failed"
        or (item["state"] == "completed" and isinstance(item.get("valid"), bool))
    ]
    exact = [
        item
        for item in items
        if (item["state"] == "completed" and isinstance(item.get("exact_valid"), bool))
        or (
            item["state"] == "failed"
            and item.get("evaluation_version") == EVALUATION_VERSION
        )
    ]
    coverage = [
        item["coverage"]
        for item in completed
        if item.get("coverage") is not None
        and item.get("evaluation_version") == EVALUATION_VERSION
    ]
    fidelity = [
        item["exact_coverage"]
        for item in completed
        if item.get("exact_coverage") is not None
    ]
    return {
        "pass_rate": sum(item.get("valid") is True for item in processed)
        / len(processed)
        if processed
        else None,
        "mean_word_coverage": sum(coverage) / len(coverage) if coverage else None,
        "exact_valid": sum(item.get("exact_valid") is True for item in exact),
        "exact_evaluated": len(exact),
        "exact_pass_rate": sum(item.get("exact_valid") is True for item in exact)
        / len(exact)
        if exact
        else None,
        "mean_exact_word_coverage": sum(fidelity) / len(fidelity) if fidelity else None,
    }


def category_summary(items):
    groups = {}
    for item in items:
        groups.setdefault(item["category"], []).append(item)
    categories = []
    for category, records in sorted(groups.items()):
        valid = sum(
            item["state"] == "completed" and item.get("valid") is True
            for item in records
        )
        invalid = sum(
            item["state"] == "completed" and item.get("valid") is False
            for item in records
        )
        errors = sum(item["state"] == "failed" for item in records)
        processed = valid + invalid + errors
        categories.append(
            {
                "id": category,
                "total": len(records),
                "valid": valid,
                "invalid": invalid,
                "errors": errors,
                "pending": sum(
                    item["state"] in {"queued", "running"} for item in records
                ),
                "cancelled": sum(item["state"] == "cancelled" for item in records),
                "processed": processed,
                "success_rate": valid / processed if processed else None,
                **word_summary(records),
            }
        )
    return categories


def summarize(items):
    effects = {
        key: {
            "id": key,
            "label": label,
            "comparisons": 0,
            "improved": 0,
            "unchanged": 0,
            "worse": 0,
            "recovered": 0,
            "delta_sum": 0.0,
        }
        for key, label in EFFECT_LABELS.items()
    }
    for item in items:
        for effect in item.get("effects", []):
            for key in (
                "comparisons",
                "improved",
                "unchanged",
                "worse",
                "recovered",
                "delta_sum",
            ):
                effects[effect["id"]][key] += effect[key]
    return {
        "total": len(items),
        **word_summary(items),
        "valid": sum(
            item["state"] == "completed" and item.get("valid") is True for item in items
        ),
        "invalid": sum(
            item["state"] == "completed" and item.get("valid") is False
            for item in items
        ),
        "errors": sum(item["state"] == "failed" for item in items),
        "pending": sum(item["state"] in {"queued", "running"} for item in items),
        "cancelled": sum(item["state"] == "cancelled" for item in items),
        "effects": list(effects.values()),
        "categories": category_summary(items),
    }
