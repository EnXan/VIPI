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
import subprocess

from research.catalog import CATALOG_NAME
from research.ocr_eval import benchmark
from vipi import config
from vipi.ocr.models import REQUIRED as OCR_FILES_BY_MODEL

from . import splits

CONFIGURATIONS = benchmark.CONFIGURATIONS
METRIC_SOURCES = (
    "research/ocr_eval/evaluation/metrics.py",
    "research/ocr_eval/evaluation/words.py",
    "research/ocr_eval/benchmark_report.py",
)
BASELINES = Path("research/baselines")
OCR_REGISTRY = "src/vipi/ocr/model_files.json"
DECISION_REGISTRY = "src/vipi/decision_models.json"
MODEL_REGISTRIES = (OCR_REGISTRY, DECISION_REGISTRY)
DECISION_MODEL_FIELDS = ("repository", "revision", "code")
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


def used_registry_entries(scan_options, registries):
    """The registry entries a configuration actually loads (ADR 0060).

    OCR files of the resolved OCR model; repository, revision and code hashes of
    the local decision models it uses for review and detection. Other entries,
    such as a newly added model, do not change a configuration's identity."""
    options = config.ScanOptions(**scan_options)
    ocr = registries[OCR_REGISTRY]
    decisions = registries[DECISION_REGISTRY]
    names = sorted(
        {options.resolved_decision_provider, options.resolved_detector} & set(decisions)
    )
    return {
        OCR_REGISTRY: {
            key: ocr[key]
            for key in OCR_FILES_BY_MODEL.get(options.resolved_ocr_model, ())
        },
        DECISION_REGISTRY: {
            name: {field: decisions[name][field] for field in DECISION_MODEL_FIELDS}
            for name in names
        },
    }


def detector_models(scan_options):
    """Pinned detectors outside the registries, only when the configuration uses them."""
    if config.ScanOptions(**scan_options).resolved_detector != "prompt-guard":
        return {}
    from vipi.detection.providers.prompt_guard import MODEL_ID

    return {
        "detector_models": {
            "prompt-guard": {
                "repository": MODEL_ID,
                "revision": config.PROMPT_GUARD_REVISION,
            }
        }
    }


def model_identity(root, scan_options):
    constants = {
        name: getattr(config, name)
        for name in sorted(dir(config))
        if name.endswith("_MODEL") and isinstance(getattr(config, name), str)
    }
    registries = {
        source: json.loads((Path(root) / source).read_text(encoding="utf-8"))
        for source in MODEL_REGISTRIES
    }
    return {
        "constants": constants,
        "registries": used_registry_entries(scan_options, registries),
        **detector_models(scan_options),
    }


def file_at_commit(root, commit, path):
    """Bytes of ``path`` at ``commit``, or None when git cannot provide them."""
    try:
        return subprocess.run(
            ["git", "show", f"{commit}:{path}"],
            cwd=root,
            check=True,
            capture_output=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return None


def comparable(manifest_value, implementation, root=benchmark.ROOT):
    """Express a manifest recorded with whole-registry hashes per used entry.

    Manifests before ADR 0060 recorded a SHA-256 of each registry file. The file
    is read from git at the recorded commit and used only if its SHA-256 equals
    the recorded hash; otherwise the manifest is returned unchanged and compares
    as different. Current manifests are returned unchanged."""
    identity = manifest_value.get("configuration", {}).get("model_identity", {})
    recorded = identity.get("registries", {})
    commit = (implementation or {}).get("commit")
    if (
        not commit
        or not recorded
        or not all(isinstance(value, str) for value in recorded.values())
    ):
        return manifest_value
    registries = {}
    for path in MODEL_REGISTRIES:
        content = file_at_commit(root, commit, path)
        if content is None or hashlib.sha256(content).hexdigest() != recorded.get(path):
            return manifest_value
        registries[path] = json.loads(content)
    configuration = manifest_value["configuration"]
    return {
        **manifest_value,
        "configuration": {
            **configuration,
            "model_identity": {
                **identity,
                "registries": used_registry_entries(
                    configuration["scan_options"], registries
                ),
            },
        },
    }


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
            "model_identity": model_identity(root, CONFIGURATIONS[name]),
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
    changed = differences(
        comparable(latest["manifest"], latest.get("implementation"), root), current
    )
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
