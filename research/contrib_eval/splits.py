"""Assign both pinned catalogs to disjoint, grouped development/test splits.

Entries that share content are grouped so variants never straddle the splits:
OCR entries by source ``content_group_id``, detection images by exact payload
and by filename family (the stem without its trailing obfuscation suffix), and
any entries whose image bytes are identical, including across catalogs. Groups
are ranked per stratum by a seeded SHA-256 and the lowest-ranked groups fill
the test split up to the configured fraction of that stratum's entries.
"""

from collections import defaultdict
import hashlib
import json
from pathlib import Path

from research.ocr_eval.benchmark import ROOT, catalogs, digest

ALGORITHM = "grouped_stratified_sha256_rank_v1"
SEED = "vipi-contribution-evaluation-v1"
TEST_FRACTION = 0.2
SPLITS_PATH = Path("research/splits.json")


def sha256_text(value):
    return hashlib.sha256(value.encode()).hexdigest()


def filename_family(image, obfuscation_tokens):
    """Strip trailing ``none``/obfuscation tokens from a detection filename stem."""
    parts = Path(image).stem.split("_")
    while len(parts) > 1 and parts[-1] in obfuscation_tokens:
        parts.pop()
    return "_".join(parts)


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
                "tokens": [
                    f"image:{image_sha256}",
                    f"ocr_content:{item['source']['content_group_id']}",
                ],
            }
        )
    for identifier, item in detection.items.items():
        image_sha256 = digest(detection.path(identifier))
        entries.append(
            {
                "key": f"detection_eval:{identifier}",
                "stratum": f"detection_eval:{item['category']}",
                "image_sha256": image_sha256,
                "tokens": [
                    f"image:{image_sha256}",
                    f"payload:{sha256_text(item['text'])}",
                    f"family:{filename_family(item['image'], obfuscation_tokens)}",
                ],
            }
        )
    return entries


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
