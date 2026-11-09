"""Identify what an evaluation measures and find its saved baseline.

A manifest has two parts. ``suite`` covers what is evaluated: dataset revision,
catalog, split file, the selected entries with their image/reference hashes,
and the metric sources. ``configuration`` covers how the scan runs: the product
scan options and the declared model identity. Implementation provenance is
deliberately excluded: a change differs from its baseline by design.
"""

import hashlib
import json
from pathlib import Path

from research.catalog import CATALOG_NAME
from research.ocr_eval import benchmark
from vipi import config

from . import splits

CONFIGURATIONS = benchmark.CONFIGURATIONS
METRIC_SOURCES = (
    "research/ocr_eval/evaluation/metrics.py",
    "research/ocr_eval/evaluation/words.py",
    "research/ocr_eval/benchmark_report.py",
)
BASELINES = Path("research/baselines")
MODEL_REGISTRIES = ("src/vipi/ocr/model_files.json", "src/vipi/decision_models.json")
SPLIT_NAMES = ("development", "test")
SUMMARY_KIND = "vipi-evaluation-run"


def json_sha256(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def check_configuration(name):
    if name not in CONFIGURATIONS:
        raise ValueError(
            f"Unknown configuration {name!r}; choose {', '.join(CONFIGURATIONS)}."
        )
    return name


def selected_rows(root, split):
    """Return benchmark selection rows assigned to ``split``, in catalog order."""
    if split not in SPLIT_NAMES:
        raise ValueError(f"Choose split {' or '.join(SPLIT_NAMES)}.")
    document = splits.load(root)
    rows = benchmark.selection(root)
    unassigned = [row["key"] for row in rows if row["key"] not in document["entries"]]
    if unassigned:
        raise ValueError(
            f"{len(unassigned)} catalog entries have no split assignment; "
            "regenerate research/splits.json."
        )
    for row in rows:
        if row["image_sha256"] != document["entries"][row["key"]]["image_sha256"]:
            raise ValueError(f"Image changed since the split was built: {row['key']}")
    return [row for row in rows if document["entries"][row["key"]]["split"] == split]


def model_identity(root):
    constants = {
        name: getattr(config, name)
        for name in sorted(dir(config))
        if name.endswith("_MODEL") and isinstance(getattr(config, name), str)
    }
    registries = {
        source: benchmark.digest(Path(root) / source) for source in MODEL_REGISTRIES
    }
    return {"constants": constants, "registries": registries}


def manifest(name, split="development", root=benchmark.ROOT):
    """Return the identity of configuration ``name`` on ``split`` for this checkout."""
    root = Path(root)
    check_configuration(name)
    rows = selected_rows(root, split)
    selection = [
        [row["key"], row["image_sha256"], row["reference_sha256"]] for row in rows
    ]
    return {
        "configuration_name": name,
        "split": split,
        "suite": {
            "dataset": json.loads((root / "research/dataset.json").read_text()),
            "catalog_sha256": benchmark.digest(
                benchmark.dataset_directory(root) / CATALOG_NAME
            ),
            "splits_sha256": benchmark.digest(root / splits.SPLITS_PATH),
            "entries": len(selection),
            "selection_sha256": json_sha256(selection),
            "metric_sha256": {
                source: benchmark.digest(root / source) for source in METRIC_SOURCES
            },
        },
        "configuration": {
            "scan_options": CONFIGURATIONS[name],
            "model_identity": model_identity(root),
        },
    }


def differences(expected, actual, prefix=""):
    """List dotted field paths whose values differ between two manifests."""
    if isinstance(expected, dict) and isinstance(actual, dict):
        changed = []
        for key in sorted(set(expected) | set(actual)):
            changed += differences(
                expected.get(key), actual.get(key), f"{prefix}{key}."
            )
        return changed
    return [] if expected == actual else [prefix.rstrip(".")]


def latest_baseline(name, split, root=benchmark.ROOT):
    """Return ``(path, summary)`` of the newest saved baseline, or None."""
    found = []
    for path in sorted((Path(root) / BASELINES).glob("*.json")):
        summary = json.loads(path.read_text(encoding="utf-8"))
        if (
            summary.get("kind") == SUMMARY_KIND
            and summary["manifest"]["configuration_name"] == name
            and summary["manifest"]["split"] == split
        ):
            found.append((path, summary))
    return max(found, key=lambda item: item[1]["completed_at"], default=None)


def status(name, split="development", root=benchmark.ROOT):
    """Compare the latest saved baseline with the current manifest."""
    root = Path(root)
    current = manifest(name, split, root)
    found = latest_baseline(name, split, root)
    if not found:
        return {"state": "none", "configuration": name, "split": split}
    path, latest = found
    changed = differences(latest["manifest"], current)
    return {
        "state": "stale" if changed else "fresh",
        "configuration": name,
        "split": split,
        "baseline": {
            "summary": path.relative_to(root).as_posix(),
            "run_id": latest["run_id"],
            "completed_at": latest["completed_at"],
        },
        "differences": changed,
    }
