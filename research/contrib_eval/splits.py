"""Assign the evaluation dataset to disjoint, grouped development/test splits.

Entries that share content are grouped so variants never straddle the splits:
identical images, the same source content group, the same visible text, texts
that share at least 80% of their words (template variants that differ in one
slot word), the same scenario family of former detection fixtures (filename
without its obfuscation suffix) and listed matched-control pairs. Groups are
ranked per label × content stratum by a seeded SHA-256 and the lowest-ranked
groups fill the test split up to the configured fraction of that stratum.
"""

from collections import defaultdict
import hashlib
import json
from pathlib import Path
import re

from research.catalog import CATALOG_NAME
from research.ocr_eval.benchmark import ROOT, catalog, dataset_directory, digest

ALGORITHM = "grouped_stratified_sha256_rank_v3"
SEED = "vipi-contribution-evaluation-v1"
TEST_FRACTION = 0.2
SPLITS_PATH = Path("research/splits.json")
# Word-set Jaccard similarity that joins two texts into one group. Observed
# vpi_bench slot variants score 0.88-0.94; unrelated texts stay far below.
TEXT_SIMILARITY = 0.8
# Shorter texts are too generic for a similarity match; exact identity still
# groups them through payload or image hashes.
TEXT_MIN_WORDS = 5
# Benign controls kept with their attacks. Anamorpher is documented in the
# detection README; the other pairs were identified from scenario filenames and
# confirmed by the maintainer on 2026-11-07.
CONTROL_GROUPS = {
    "anamorpher": (
        "anamorpher_0000_blue-code_benign_image-scaling",
        "anamorpher_0001_orange_instruction-override-task-redirection_image-scaling",
        "anamorpher_1419_orange_instruction-override-task-redirection_image-scaling",
    ),
    "architecture-private-report-upload": (
        "synthetic_architecture_private-report-upload_authenticated-control_none",
        "synthetic_architecture_private-report-upload_auth-bypass_contextual-camouflage-instruction-override-task-redirection_none",
    ),
    "vendor-onboarding-dpa": (
        "synthetic_vendor-onboarding_dpa-follow-up_benign_none",
        "synthetic_vendor-onboarding_dpa-missing_suppression_contextual-camouflage-instruction-override-task-redirection_none",
    ),
    "sting-readme": ("sting_readme_benign_setup", "sting_readme_setup_note"),
    "sting-terminal": ("sting_terminal_benign_diagnostic", "sting_terminal_warning"),
    "sting-vscode": ("sting_vscode_benign_comment", "sting_vscode_review_comment"),
    "sting-dependency": (
        "sting_dependency_benign_guidance",
        "sting_dependency_compliance_note",
    ),
}
CONTROL_BY_STEM = {
    stem: name for name, stems in CONTROL_GROUPS.items() for stem in stems
}
# obfuscation suffixes used in the former detection fixture filenames
OBFUSCATION_TOKENS = {
    "blur", "distorted-text", "high-transparency", "image-scaling", "italic-font",
    "low-contrast", "mirrored-text", "rotated-text", "small-font", "split-text",
    "unicode-homoglyphs", "base64", "flowchart",
}  # fmt: skip


def sha256_text(value):
    return hashlib.sha256(value.encode()).hexdigest()


def filename_family(image):
    """Strip trailing ``none``/obfuscation tokens from a former detection
    filename stem (``…_contextual-camouflage_low-contrast`` → scenario)."""
    parts = Path(image).stem.split("_")
    while len(parts) > 1 and (parts[-1] == "none" or parts[-1] in OBFUSCATION_TOKENS):
        parts.pop()
    return "_".join(parts)


def text_words(text):
    return sorted(set(re.findall(r"\w+", text.casefold())))


def similar_text_tokens(entries, threshold=TEXT_SIMILARITY, min_words=TEXT_MIN_WORDS):
    """Return entries with a shared token added for each similar text pair."""
    sets = [set(entry.get("words", ())) for entry in entries]
    added = defaultdict(list)
    for first in range(len(entries)):
        if len(sets[first]) < min_words:
            continue
        for second in range(first + 1, len(entries)):
            other = sets[second]
            if len(other) < min_words:
                continue
            union = len(sets[first] | other)
            if len(sets[first] & other) >= threshold * union:
                token = f"text:{entries[first]['key']}"
                added[first].append(token)
                added[second].append(token)
    return [
        {**entry, "tokens": [*entry["tokens"], *added[index]]}
        for index, entry in enumerate(entries)
    ]


def visible_text(entry):
    return (entry["ocr_reference"] or {}).get("text") or entry["payload"] or ""


def collect_entries(root=ROOT):
    """Read the dataset and return one grouping record per entry."""
    dataset = catalog(root)
    entries = []
    for identifier, item in dataset.items.items():
        image_sha256 = digest(dataset.path(identifier))
        text = visible_text(item)
        tokens = [f"image:{image_sha256}"]
        if item["source"].get("content_group_id"):
            tokens.append(f"content:{item['source']['content_group_id']}")
        if text.strip():
            tokens.append(f"text:{sha256_text(' '.join(text.casefold().split()))}")
        former = (item.get("migrated_from") or {}).get("detection_eval") or {}
        if former.get("image"):
            stem = Path(former["image"]).stem
            tokens.append(f"family:{filename_family(former['image'])}")
            if stem in CONTROL_BY_STEM:
                tokens.append(f"control:{CONTROL_BY_STEM[stem]}")
        entries.append(
            {
                "key": identifier,
                "stratum": f"{item['label']}:{item['content']}",
                "image_sha256": image_sha256,
                "words": text_words(text),
                "tokens": tokens,
            }
        )
    return similar_text_tokens(entries)


def group_entries(entries):
    """Union entries sharing any grouping token; return member-key lists."""
    parent = {entry["key"]: entry["key"] for entry in entries}

    def find(key):
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key

    owner = {}
    for entry in entries:
        for token in entry["tokens"]:
            if token in owner:
                first, second = find(owner[token]), find(entry["key"])
                if first != second:
                    parent[max(first, second)] = min(first, second)
            else:
                owner[token] = entry["key"]
    groups = defaultdict(list)
    for entry in entries:
        groups[find(entry["key"])].append(entry["key"])
    return [sorted(members) for members in groups.values()]


def assign(entries, seed=SEED, test_fraction=TEST_FRACTION):
    """Return ``{key: (split, group_id)}`` with disjoint, grouped splits."""
    by_key = {entry["key"]: entry for entry in entries}
    if len(by_key) != len(entries):
        raise ValueError("Split entries require unique keys.")
    strata = defaultdict(list)
    for members in group_entries(entries):
        group_id = sha256_text("\n".join(members))[:16]
        stratum = "|".join(sorted({by_key[key]["stratum"] for key in members}))
        strata[stratum].append((sha256_text(f"{seed}:{group_id}"), group_id, members))
    assignments = {}
    for stratum in sorted(strata):
        groups = sorted(strata[stratum])
        target = round(test_fraction * sum(len(g[2]) for g in groups))
        held = 0
        for _rank, group_id, members in groups:
            split = "development"
            if held + len(members) <= target:
                split = "test"
                held += len(members)
            for key in members:
                assignments[key] = (split, group_id)
    return assignments


def build(root=ROOT, seed=SEED, test_fraction=TEST_FRACTION):
    """Build the complete split document for the dataset."""
    root = Path(root)
    entries = collect_entries(root)
    assignments = assign(entries, seed, test_fraction)
    counts = {"development": defaultdict(int), "test": defaultdict(int)}
    groups = {"development": set(), "test": set()}
    for entry in entries:
        split, group_id = assignments[entry["key"]]
        counts[split][entry["stratum"]] += 1
        groups[split].add(group_id)
    return {
        "version": 1,
        "dataset": json.loads((root / "research/dataset.json").read_text()),
        "catalog_sha256": digest(dataset_directory(root) / CATALOG_NAME),
        "policy": {
            "algorithm": ALGORITHM,
            "seed": seed,
            "test_fraction": test_fraction,
            "grouping": [
                "identical_image_sha256",
                "source_content_group_id",
                "identical_visible_text",
                f"text_word_jaccard_at_least_{TEXT_SIMILARITY}_min_{TEXT_MIN_WORDS}_words",
                "former_detection_filename_family_without_obfuscation_suffix",
                "matched_control_pairs",
            ],
            "stratification": "label x content",
            "usage": "Development for every comparison; test only for a one-time "
            "confirmation before a default, profile or threshold changes.",
        },
        "counts": {
            split: {
                "entries": sum(values.values()),
                "groups": len(groups[split]),
                "by_stratum": dict(sorted(values.items())),
            }
            for split, values in counts.items()
        },
        "entries": {
            entry["key"]: {
                "split": assignments[entry["key"]][0],
                "group": assignments[entry["key"]][1],
                "image_sha256": entry["image_sha256"],
            }
            for entry in sorted(entries, key=lambda entry: entry["key"])
        },
    }


def serialize(document):
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


def write(root=ROOT):
    path = Path(root) / SPLITS_PATH
    path.write_text(serialize(build(root)), encoding="utf-8")
    return path


def check(root=ROOT):
    """Return True when the committed split matches the current dataset."""
    path = Path(root) / SPLITS_PATH
    return path.is_file() and path.read_text(encoding="utf-8") == serialize(build(root))


def load(root=ROOT):
    return json.loads((Path(root) / SPLITS_PATH).read_text(encoding="utf-8"))
