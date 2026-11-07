"""Identify an evaluation path's frozen suite and check baseline freshness.

A manifest has two parts. ``suite`` covers what is evaluated: dataset revision,
catalogs, split file, the selected cases with their image/reference hashes, and
the metric sources. ``configuration`` covers how the path runs: the benchmark
configuration and the declared model identity. Implementation provenance is
deliberately excluded: a candidate differs from its baseline by design.
"""

import hashlib
import json
from pathlib import Path

from research.ocr_eval import benchmark
from vipi import config

from . import splits

PATHS = {
    "ocr/cloud-default": {
        "benchmark_configuration": "cloud-default",
        "metric_sources": (
            "research/ocr_eval/evaluation/metrics.py",
            "research/ocr_eval/evaluation/words.py",
            "research/ocr_eval/benchmark_report.py",
        ),
        "reports": "research/ocr_eval/reports/contrib",
    },
    "ocr/local-speed": {
        "benchmark_configuration": "local-speed",
        "metric_sources": (
            "research/ocr_eval/evaluation/metrics.py",
            "research/ocr_eval/evaluation/words.py",
            "research/ocr_eval/benchmark_report.py",
        ),
        "reports": "research/ocr_eval/reports/contrib",
    },
}
MODEL_REGISTRIES = ("src/vipi/ocr/model_files.json", "src/vipi/decision_models.json")
SPLIT_NAMES = ("development", "test")
SUMMARY_KIND = "vipi-contribution-run"


def json_sha256(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def path_definition(name):
    if name not in PATHS:
        raise ValueError(f"Unknown evaluation path {name!r}; choose {sorted(PATHS)}.")
    return PATHS[name]


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
    """Return the identity of path ``name`` on ``split`` for the current checkout."""
    root = Path(root)
    definition = path_definition(name)
    rows = selected_rows(root, split)
    selection = [
        [row["key"], row["image_sha256"], row["reference_sha256"]] for row in rows
    ]
    configuration_name = definition["benchmark_configuration"]
    return {
        "path": name,
        "split": split,
        "suite": {
            "dataset": json.loads((root / "research/dataset.json").read_text()),
            "catalog_sha256": {
                "ocr_eval": benchmark.digest(root / "research/ocr_eval/catalog.json"),
                "detection_eval": benchmark.digest(
                    root / "research/detection_eval/cases.json"
                ),
            },
            "splits_sha256": benchmark.digest(root / splits.SPLITS_PATH),
            "entries": len(selection),
            "selection_sha256": json_sha256(selection),
            "metric_sha256": {
                source: benchmark.digest(root / source)
                for source in definition["metric_sources"]
            },
        },
        "configuration": {
            "benchmark_configuration": {
                configuration_name: benchmark.CONFIGURATIONS[configuration_name]
            },
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


def baseline_summaries(name, split, root):
    """Yield committed baseline summaries for ``name``/``split``."""
    directory = Path(root) / path_definition(name)["reports"]
    for path in sorted(directory.glob("*.json")):
        summary = json.loads(path.read_text(encoding="utf-8"))
        if (
            summary.get("kind") == SUMMARY_KIND
            and summary.get("role") == "baseline"
            and summary["manifest"]["path"] == name
            and summary["manifest"]["split"] == split
        ):
            yield path, summary


def status(name, split="development", root=benchmark.ROOT):
    """Compare the latest committed baseline with the current manifest."""
    root = Path(root)
    current = manifest(name, split, root)
    found = sorted(
        baseline_summaries(name, split, root),
        key=lambda item: item[1]["completed_at"],
    )
    if not found:
        return {"state": "none", "path": name, "split": split, "current": current}
    path, latest = found[-1]
    changed = differences(latest["manifest"], current)
    return {
        "state": "stale" if changed else "fresh",
        "path": name,
        "split": split,
        "baseline": {
            "summary": path.relative_to(root).as_posix(),
            "run_id": latest["run_id"],
            "completed_at": latest["completed_at"],
        },
        "differences": changed,
        "current": current,
    }
