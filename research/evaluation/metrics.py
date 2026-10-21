"""Reference coverage: extra OCR text is allowed; spelling errors are not."""

import re
import unicodedata
from collections import Counter

from vipi.ocr.merge import bounds

EVALUATION_VERSION = 2
EFFECT_LABELS = {
    "scaling": "Skalierung",
    "rotation": "Rotation",
    "tiling": "Kacheln",
    "grayscale": "Graustufen",
    "clahe": "CLAHE",
    "inverted": "Invertierung",
    "threshold": "Threshold",
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


def region_matches(reference, observations):
    """One-to-one token matching in overlapping input-coordinate word regions."""
    expected = [
        (token, bounds(region["input_polygon"]))
        for region in reference["regions"]
        for token in tokens(region["text"])
    ]
    observed = [
        (token, bounds(region["input_polygon"]))
        for region in observations
        if region.get("input_polygon")
        for token in tokens(region["text"])
    ]

    edges = []
    ordered_positions, offset = set(), 0
    for region in reference["regions"]:
        unit = tokens(region["text"])
        local = [
            token
            for token, box in observed
            if box_overlap(bounds(region["input_polygon"]), box) >= 0.5
        ]
        ordered_positions.update(
            offset + index for index in ordered_matches(unit, local)
        )
        offset += len(unit)
    for index, (token, box) in enumerate(expected):
        scores = [
            (box_overlap(box, candidate), j)
            for j, (text, candidate) in enumerate(observed)
            if text == token
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
    if reference["reading_order_known"]:
        expected = tokens(reference["text"])
        matched = ordered_matches(expected, tokens(text))
    else:
        if not reference["regions"]:
            raise ValueError("Unordered references require annotated word regions.")
        expected, matched = region_matches(reference, regions)
    return score(expected, matched), expected, matched


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
            baseline = by_view[(step["view_id"], "unchanged")]
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


def evaluate(reference, text, regions, variants):
    evaluations, all_matched = {}, set()
    for step in variants:
        result, expected, matched = compare(reference, step["text"], step["regions"])
        evaluations[step["id"]] = result
        all_matched.update(matched)
    final_regions = (
        regions
        if reference["reading_order_known"]
        else final_observations(regions, variants)
    )
    final, expected, final_matched = compare(reference, text, final_regions)
    best = max(
        variants, key=lambda step: (evaluations[step["id"]]["matched"], -step["index"])
    )
    best_score = evaluations[best["id"]]
    if reference["reading_order_known"]:
        detection = final if final["matched"] > best_score["matched"] else best_score
    else:
        detection = score(expected, all_matched | final_matched)
    return {
        "version": EVALUATION_VERSION,
        "reference": reference,
        "method": "ordered_tokens"
        if reference["reading_order_known"]
        else "word_regions",
        "valid": detection["valid"],
        "detection": detection,
        "final": final,
        "original": evaluations[variants[0]["id"]],
        "best_step_id": best["id"],
        "best_label": best["label"],
        "valid_step_ids": [
            step["id"] for step in variants if evaluations[step["id"]]["valid"]
        ],
        "steps": evaluations,
        "effects": effect_summary(evaluations, variants),
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
                "processed": processed,
                "success_rate": valid / processed if processed else None,
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
        "valid": sum(item.get("valid") is True for item in items),
        "invalid": sum(item.get("valid") is False for item in items),
        "errors": sum(item["state"] == "failed" for item in items),
        "pending": sum(item["state"] in {"queued", "running"} for item in items),
        "effects": list(effects.values()),
        "categories": category_summary(items),
    }
