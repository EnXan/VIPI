"""Assign both pinned catalogs to disjoint, grouped development/test splits.

Entries that share content are grouped so variants never straddle the splits:
OCR entries by source ``content_group_id``, detection images by exact payload,
by filename family (the stem without its trailing obfuscation suffix) and by
listed matched-control pairs, entries whose image bytes are identical, and
entries whose texts share at least 80% of their words, including across
catalogs (template variants that differ in one slot word). Groups
are ranked per stratum by a seeded SHA-256 and the lowest-ranked groups fill
the test split up to the configured fraction of that stratum's entries.
"""

from collections import defaultdict
import hashlib
import json
from pathlib import Path
import re

from research.ocr_eval.benchmark import ROOT, catalogs, digest

ALGORITHM = "grouped_stratified_sha256_rank_v2"
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


def sha256_text(value):
    return hashlib.sha256(value.encode()).hexdigest()


def filename_family(image, obfuscation_tokens):
    """Strip trailing ``none``/obfuscation tokens from a detection filename stem."""
    parts = Path(image).stem.split("_")
    while len(parts) > 1 and parts[-1] in obfuscation_tokens:
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


def collect_entries(root=ROOT):
    """Read both catalogs and return one grouping record per entry."""
    loaded = catalogs(root)
    detection = loaded["detection_eval"]
    obfuscation_tokens = {"none"} | {
        label.replace("_", "-")
        for item in detection.items.values()
        for label in item["obfuscation"]
    }
    entries = []
    for identifier, item in loaded["ocr_eval"].items.items():
        image_sha256 = digest(loaded["ocr_eval"].path(identifier))
        entries.append(
            {
                "key": f"ocr_eval:{identifier}",
                "stratum": f"ocr_eval:{item['category']}",
                "image_sha256": image_sha256,
                "words": text_words(item["text"]),
                "tokens": [f"image:{image_sha256}"]
                + (
                    [f"ocr_content:{item['source']['content_group_id']}"]
                    if item.get("source", {}).get("content_group_id")
                    else []
                ),
            }
        )
    for identifier, item in detection.items.items():
        image_sha256 = digest(detection.path(identifier))
        entries.append(
            {
                "key": f"detection_eval:{identifier}",
                "stratum": f"detection_eval:{item['category']}",
                "image_sha256": image_sha256,
                "words": text_words(item["text"]),
                "tokens": [
                    f"image:{image_sha256}",
                    f"payload:{sha256_text(item['text'])}",
                    f"family:{filename_family(item['image'], obfuscation_tokens)}",
                ]
                + (
                    [f"control:{CONTROL_BY_STEM[Path(item['image']).stem]}"]
                    if Path(item["image"]).stem in CONTROL_BY_STEM
                    else []
                ),
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
    """Build the complete split document for the pinned catalogs."""
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
        "catalog_sha256": {
            "ocr_eval": digest(root / "research/ocr_eval/catalog.json"),
            "detection_eval": digest(root / "research/detection_eval/cases.json"),
        },
        "policy": {
            "algorithm": ALGORITHM,
            "seed": seed,
            "test_fraction": test_fraction,
            "grouping": [
                "identical_image_sha256_across_catalogs",
                "ocr_source_content_group_id",
                "detection_identical_payload_sha256",
                "detection_filename_family_without_obfuscation_suffix",
                "detection_matched_control_pairs",
                f"text_word_jaccard_at_least_{TEXT_SIMILARITY}_min_{TEXT_MIN_WORDS}_words",
            ],
            "stratification": "catalog category (OCR) or label category (detection)",
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
    """Return True when the committed split matches the current catalogs."""
    path = Path(root) / SPLITS_PATH
    return path.is_file() and path.read_text(encoding="utf-8") == serialize(build(root))


def load(root=ROOT):
    return json.loads((Path(root) / SPLITS_PATH).read_text(encoding="utf-8"))
