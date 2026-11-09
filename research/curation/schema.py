"""Validate the combined catalog against its vocabulary and report label counts."""

from collections import Counter
from pathlib import Path

from research.ocr_eval.benchmark import digest

from .similarity import text_templates
from .vocabulary import FIELDS, LABELS, allowed

ENTRY_KEYS = {
    "id",
    "image",
    "image_sha256",
    *FIELDS,
    "payload",
    "cases",
    "ocr_reference",
    "source",
    "migrated_from",
    "curation",
}
REQUIRED_WHEN_REVIEWED = ("label", "content")
MINIMUM_PER_VALUE = 10
# ADR 0051 composition rule 3: further copies of one text template add weight,
# not new cases.
MAXIMUM_PER_TEMPLATE = 3
# ADR 0051 composition rule 1: attacks and benign images in similar numbers
# within every content type.
TARGET_BENIGN_PERCENT = 50.0
DECISIONS = ("keep", "drop")


def field_errors(entry, vocabulary):
    errors = []
    label = entry.get("label")
    for field in FIELDS:
        spec = vocabulary["fields"][field]
        value = entry.get(field)
        values = value if isinstance(value, list) else [] if value is None else [value]
        if spec["multiple"] and not isinstance(value, list):
            errors.append(f"{field} must be a list")
            continue
        if not spec["multiple"] and isinstance(value, list):
            errors.append(f"{field} takes one value")
            continue
        unknown = sorted(set(values) - allowed(vocabulary, field))
        if unknown:
            errors.append(f"{field} has values outside the vocabulary: {unknown}")
        if values and label is not None and label not in spec["applies_to"]:
            errors.append(f"{field} does not apply to label {label!r}")
    return errors


def entry_errors(entry, vocabulary, ids):
    errors = []
    missing = sorted(ENTRY_KEYS - set(entry))
    extra = sorted(set(entry) - ENTRY_KEYS)
    if missing:
        errors.append(f"missing keys {missing}")
    if extra:
        errors.append(f"unknown keys {extra}")
    if missing:
        return errors
    errors += field_errors(entry, vocabulary)
    for case in entry["cases"]:
        if case.get("expected") not in LABELS:
            errors.append(f"case expected must be one of {LABELS}")
    curation = entry["curation"]
    if curation.get("decision") not in DECISIONS:
        errors.append(f"curation decision must be one of {DECISIONS}")
    if curation.get("decision") == "drop" and not curation.get("reason"):
        errors.append("a dropped entry needs a reason")
    if curation.get("duplicate_of") and curation["duplicate_of"] not in ids:
        errors.append(f"duplicate_of refers to unknown id {curation['duplicate_of']}")
    if curation.get("reviewed"):
        for field in REQUIRED_WHEN_REVIEWED:
            if entry.get(field) is None:
                errors.append(f"reviewed entry needs {field}")
    return errors


def validate(catalog, vocabulary, images_root=None):
    """Return ``(errors, warnings)`` as lists of ``"<id>: message"`` strings."""
    errors, warnings = [], []
    ids = Counter(entry.get("id") for entry in catalog)
    errors += [f"{key}: duplicate id" for key, count in ids.items() if count > 1]
    kept = [e for e in catalog if e.get("curation", {}).get("decision") != "drop"]
    hashes = Counter(entry.get("image_sha256") for entry in kept)
    for entry in catalog:
        key = entry.get("id", "<no id>")
        errors += [
            f"{key}: {message}" for message in entry_errors(entry, vocabulary, ids)
        ]
        if entry in kept and hashes[entry.get("image_sha256")] > 1:
            errors.append(f"{key}: identical image kept twice; drop one")
        if not (entry.get("source") or {}).get("license"):
            warnings.append(f"{key}: license unknown")
        # dropped entries stay as a record (reason, duplicate_of, hash); their
        # image files may be deleted
        if images_root is not None and "image" in entry and entry in kept:
            path = Path(images_root) / entry["image"]
            if not path.is_file():
                errors.append(f"{key}: image missing at {path}")
            elif digest(path) != entry.get("image_sha256"):
                errors.append(f"{key}: image hash differs from catalog")
    return errors, warnings


def label_by_content(kept, vocabulary):
    """Kept images per content and label, so label imbalance is visible."""
    contents = sorted(allowed(vocabulary, "content")) + ["(unset)"]
    table = {content: {label: 0 for label in LABELS} for content in contents}
    for entry in kept:
        if entry["label"] in LABELS:
            table[entry["content"] or "(unset)"][entry["label"]] += 1
    return {content: row for content, row in table.items() if any(row.values())}


def percent(part, whole):
    return round(100 * part / whole, 1) if whole else 0.0


def balance_row(row, kept_total):
    """Shares of one content row, distance to the target and the images
    missing on the smaller side."""
    benign = row["benign"]
    attacks = sum(count for label, count in row.items() if label != "benign")
    images = benign + attacks
    benign_percent = percent(benign, images)
    return {
        "images": images,
        "dataset_percent": percent(images, kept_total),
        "labels_percent": {
            label: percent(count, images) for label, count in row.items()
        },
        "benign_percent": benign_percent,
        "attack_percent": round(100 - benign_percent, 1) if images else 0.0,
        "deviation_points": round(abs(benign_percent - TARGET_BENIGN_PERCENT), 1),
        "missing": {"benign" if benign < attacks else "attacks": abs(attacks - benign)}
        if benign != attacks
        else {},
    }


def balance(table):
    """Distance of each content and of the whole set to the benign/attack
    target; ``missing_total`` is how many images balance every content."""
    total = sum(sum(row.values()) for row in table.values())
    overall = {label: sum(row[label] for row in table.values()) for label in LABELS}
    contents = {content: balance_row(row, total) for content, row in table.items()}
    return {
        "target_benign_percent": TARGET_BENIGN_PERCENT,
        "overall": balance_row(overall, total),
        "contents": contents,
        "missing_total": {
            side: sum(row["missing"].get(side, 0) for row in contents.values())
            for side in ("benign", "attacks")
        },
    }


def values(entry, fields):
    return tuple(
        tuple(sorted(entry[field])) if isinstance(entry[field], list) else entry[field]
        for field in fields
    )


def template_text(entry):
    text = (entry["ocr_reference"] or {}).get("text") or entry["payload"]
    return " ".join(str(text or "").split())[:80]


def templates(kept):
    """Check text templates (rule 3 of ADR 0051).

    ``over_limit``: more than ``MAXIMUM_PER_TEMPLATE`` kept images with the
    same template, label and obfuscation; obfuscation is the visual variation
    that makes a repeated text a new case.
    ``inconsistent``: one template and label with differing techniques or
    goal, which the text determines; candidates for the label check.
    """
    by_id = {entry["id"]: entry for entry in kept}
    over, inconsistent = [], []
    for members in text_templates(kept):
        if len(members) < 2:
            continue
        variants = Counter(values(by_id[i], ("label", "obfuscation")) for i in members)
        for key, count in variants.items():
            if count > MAXIMUM_PER_TEMPLATE:
                ids = [
                    i
                    for i in members
                    if values(by_id[i], ("label", "obfuscation")) == key
                ]
                over.append(
                    {
                        "count": count,
                        "label": key[0],
                        "obfuscation": list(key[1]),
                        "text": template_text(by_id[ids[0]]),
                        "ids": ids,
                    }
                )
        for label in {by_id[i]["label"] for i in members}:
            ids = [i for i in members if by_id[i]["label"] == label]
            if len({values(by_id[i], ("techniques", "goal")) for i in ids}) > 1:
                inconsistent.append(
                    {
                        "count": len(ids),
                        "label": label,
                        "text": template_text(by_id[ids[0]]),
                        "ids": ids,
                    }
                )
    order = lambda item: item["count"]  # noqa: E731
    return {
        "over_limit": sorted(over, key=order, reverse=True),
        "inconsistent": sorted(inconsistent, key=order, reverse=True),
    }


def summary(catalog, vocabulary):
    """Count kept images per field value and flag values below the minimum."""
    kept = [e for e in catalog if e["curation"]["decision"] != "drop"]
    counts = {}
    for field in FIELDS:
        counter = Counter()
        for entry in kept:
            value = entry[field]
            for item in value if isinstance(value, list) else [value]:
                if item is not None:
                    counter[item] += 1
        empty = "(none)" if vocabulary["fields"][field]["multiple"] else "(unset)"
        counts[field] = {
            **{value: counter[value] for value in sorted(allowed(vocabulary, field))},
            empty: sum(not entry[field] for entry in kept),
        }
    below = {
        field: sorted(
            value
            for value, count in values.items()
            if count < MINIMUM_PER_VALUE and not value.startswith("(")
        )
        for field, values in counts.items()
    }
    return {
        "entries": len(catalog),
        "kept": len(kept),
        "dropped": len(catalog) - len(kept),
        "reviewed": sum(e["curation"]["reviewed"] for e in catalog),
        "counts": counts,
        "below_minimum": {field: values for field, values in below.items() if values},
        "label_by_content": label_by_content(kept, vocabulary),
        "balance": balance(label_by_content(kept, vocabulary)),
        "templates": templates(kept),
    }


def balance_table(data):
    """Plain-text table of ``summary()["balance"]``."""
    target = data["balance"]["target_benign_percent"]
    header = (
        f"{'content':13} {'images':>6} {'of set':>7} {'benign':>7} {'attacks':>8}"
        f" {'off target':>10}  missing to reach {target:g} % benign"
    )
    rows = [header, "-" * len(header)]
    contents = data["balance"]["contents"]
    ordered = sorted(contents.items(), key=lambda item: -item[1]["images"])
    for name, row in [*ordered, ("all", data["balance"]["overall"])]:
        if name == "all":
            rows.append("-" * len(header))
        missing = ", ".join(f"{count} {side}" for side, count in row["missing"].items())
        rows.append(
            f"{name:13} {row['images']:>6} {row['dataset_percent']:>6.1f}%"
            f" {row['benign_percent']:>6.1f}% {row['attack_percent']:>7.1f}%"
            f" {row['deviation_points']:>8.1f} pp  {missing or 'balanced'}"
        )
    missing = data["balance"]["missing_total"]
    rows.append(
        f"Balancing every content needs {missing['benign']} more benign images and "
        f"{missing['attacks']} more attacks (or as many removals on the other side)."
    )
    return "\n".join(rows)


def warning_counts(warnings):
    """Group ``"<id>: message"`` warnings by message."""
    return dict(Counter(line.split(": ", 1)[1] for line in warnings))
