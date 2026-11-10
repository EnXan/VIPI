"""Reuse results of earlier evaluation runs instead of scanning again.

For a byte-identical image, an earlier run's OCR is reused when the OCR would
be the same: the same OCR model, OCR mode and review (decision) model, the same
OCR-related product sources and runtime packages. Its detection is reused too
when, in addition, the detector, the detection settings, every product source
and every recorded package version are the same and the earlier detection
completed without errors; otherwise detection runs again. See ADR 0058 and
ADR 0064.
"""

import hashlib
import json
import os
from pathlib import Path
import shutil
import uuid

from vipi.config import ScanOptions, cache_directory
from vipi.results import OcrResult
from vipi.storage.files import write_json

# Product sources that only serve detection, input selection or the CLI; every
# other file under src/vipi/ can change the OCR result.
NOT_OCR_SOURCES = (
    "src/vipi/detection/",
    "src/vipi/inputs/",
    "src/vipi/__main__.py",
    "src/vipi/cli.py",
    "src/vipi/model_setup.py",
    "src/vipi/reporting.py",
    "src/vipi/scanner.py",
)
OCR_DETECTION_SOURCES = ("src/vipi/detection/providers/http.py",)  # used by cloud OCR
IMAGE_PACKAGES = ("Pillow", "numpy")
LOCAL_MODEL_PACKAGES = ("rapidocr", "onnxruntime", "torch", "transformers")


def digest(path):
    with Path(path).open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def ocr_identity(scan_options, provenance):
    """What determines the OCR output of a configuration in a recorded checkout."""
    options = ScanOptions(**scan_options)
    local = options.resolved_ocr_execution_mode == "local"
    sources = {
        path: value
        for path, value in provenance["source_hashes"].items()
        if path.startswith("src/vipi/")
        and (path in OCR_DETECTION_SOURCES or not path.startswith(NOT_OCR_SOURCES))
    }
    packages = IMAGE_PACKAGES + (LOCAL_MODEL_PACKAGES if local else ())
    return {
        "ocr_model": options.resolved_ocr_model,
        "ocr_mode": options.ocr_mode,
        "decision_provider": options.resolved_decision_provider,
        "sources": sources,
        "packages": {name: provenance["packages"].get(name) for name in packages},
    }


def full_identity(scan_options, provenance):
    """What determines OCR and detection: all product sources and packages."""
    options = ScanOptions(**scan_options)
    return {
        "ocr": ocr_identity(scan_options, provenance),
        "detection": options.detection_options(),
        "sources": {
            path: value
            for path, value in provenance["source_hashes"].items()
            if path.startswith("src/vipi/")
        },
        # The product's own version label is left out: its sources are compared
        # file by file above.
        "packages": {
            name: value
            for name, value in provenance["packages"].items()
            if name != "vipi-scanner"
        },
    }


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def candidates(runs_root, scan_options, provenance, exclude=None):
    """Map entry key to the best completed earlier result with the same OCR identity.

    A result whose full identity also matches and whose detection completed
    without errors carries its ``detection`` record and is preferred;
    otherwise the newest is taken. ``runs_root`` holds
    evaluation runs (``<run>/benchmark/manifest.json``); ``exclude`` is the
    benchmark directory of the current run."""
    identity = ocr_identity(scan_options, provenance)
    full = full_identity(scan_options, provenance)
    found = {}
    for manifest_path in sorted(Path(runs_root).glob("*/benchmark/manifest.json")):
        directory = manifest_path.parent
        if exclude is not None and directory.resolve() == Path(exclude).resolve():
            continue
        manifest = read_json(manifest_path)
        if not isinstance(manifest, dict):
            continue
        images = {
            row["key"]: row["image_sha256"] for row in manifest.get("selection", [])
        }
        for name, options in manifest.get("configurations", {}).items():
            try:
                if ocr_identity(options, manifest["provenance"]) != identity:
                    continue
                same_detection = full_identity(options, manifest["provenance"]) == full
            except (KeyError, TypeError, ValueError):
                continue
            for path in sorted((directory / name / "rows").glob("*.json")):
                row = read_json(path)
                if not isinstance(row, dict) or row.get("status") != "completed":
                    continue
                if not row.get("artifacts") or not row.get("result_sha256"):
                    continue
                candidate = {
                    "key": row["key"],
                    "image_sha256": images.get(row["key"]),
                    "artifacts": row["artifacts"],
                    "result_sha256": row["result_sha256"],
                    "pipeline_seconds": row.get("pipeline_seconds"),
                    "cost": row.get("cost"),
                    "finished_at": row.get("finished_at", ""),
                    "run_id": directory.parent.name,
                    "configuration": name,
                    "session": str(directory / name / "session.json"),
                    "detection": row.get("detection")
                    if same_detection and reusable_detection(row.get("detection"))
                    else None,
                    "elapsed_seconds": row.get("elapsed_seconds"),
                }
                previous = found.get(row["key"])
                if previous is None or rank(candidate) > rank(previous):
                    found[row["key"]] = candidate
    return found


def reusable_detection(detection):
    """A recorded detection that completed without errors.

    A detection that raised records its error and an "unclear" verdict; the
    cause (e.g. a missing runtime package) is not part of the identity, so
    such a detection always runs again. Errors that follow from the OCR alone
    cost nothing to recompute."""
    return isinstance(detection, dict) and not detection.get("errors")


def rank(candidate):
    return (candidate["detection"] is not None, candidate["finished_at"])


def matching(rows, found):
    """The candidates whose image is byte-identical to the selected row's image."""
    return {
        row["key"]: found[row["key"]]
        for row in rows
        if row["key"] in found
        and found[row["key"]]["image_sha256"] == row["image_sha256"]
    }


def link_or_copy(source, target):
    """Hard-link an artifact (no extra space); copy across file systems.

    Safe because artifacts are only replaced atomically (``write_json``), never
    rewritten in place, so the earlier run's files stay unchanged."""
    try:
        os.link(source, target)
    except OSError:
        shutil.copy2(source, target)


def restore(candidate, with_detection=False):
    """Copy the earlier artifacts into a new run, detection only if requested.

    Returns the OCR result, or None when the earlier artifacts are gone or
    changed; the image is then scanned again."""
    source = Path(candidate["artifacts"])
    result_path = source / "result.json"
    if not result_path.is_file() or not (source / "input.png").is_file():
        return None
    if digest(result_path) != candidate["result_sha256"]:
        return None
    run_id = uuid.uuid4().hex
    target = cache_directory() / "runs" / run_id
    ignore = None if with_detection else shutil.ignore_patterns("detection")
    shutil.copytree(source, target, ignore=ignore, copy_function=link_or_copy)
    data = json.loads(result_path.read_text(encoding="utf-8"))
    data["run_id"] = run_id
    write_json(target / "result.json", data)
    return OcrResult.from_dict(
        data, artifacts=target, image=(target / "input.png").read_bytes()
    )


def summary(directory, local):
    """Count reused rows of one configuration's benchmark directory.

    Kept outside the scored report so the metric sources (and with them every
    saved baseline) stay unchanged. Cloud cost not spent again is the reused
    rows' original OCR estimate, plus their detection estimate when detection
    was reused; local runs have no API cost."""
    rows = [read_json(path) for path in sorted(Path(directory).glob("rows/*.json"))]
    reused = [
        row for row in rows if isinstance(row, dict) and row.get("ocr_reused_from")
    ]
    whole = [row for row in reused if row["ocr_reused_from"].get("detection")]
    unspent = 0.0
    if not local:
        for row in reused:
            unspent += (row.get("cost") or {}).get("estimated_usd") or 0.0
        for row in whole:
            detection = (row.get("detection") or {}).get("cost") or {}
            unspent += detection.get("estimated_usd") or 0.0
    return {
        "images": len(reused),
        "with_detection": len(whole),
        "estimated_usd_not_spent_again": unspent,
    }


def report_lines(reuse, images):
    """Markdown lines for the run report; empty when nothing was reused."""
    if not reuse["images"]:
        return []
    whole = reuse["with_detection"]
    return [
        "",
        "## Reused results",
        "",
        f"Earlier results were reused for {reuse['images']} of {images} images "
        f"(same OCR settings, OCR sources and image): {whole} including detection "
        "(same detector, settings, product sources and packages), "
        f"{reuse['images'] - whole} with detection run again. Their time and cost "
        "are the original figures and count in the totals above; about "
        f"${reuse['estimated_usd_not_spent_again']:.2f} was not spent again "
        "(ADR 0058).",
    ]
