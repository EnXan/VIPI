"""Reuse OCR results of earlier evaluation runs instead of scanning again.

An earlier result is reused for an image only when the OCR would be the same:
the same OCR model, OCR mode and review (decision) model, the same OCR-related
product sources and runtime packages, and a byte-identical image. Detection
always runs again. See ADR 0058.
"""

import hashlib
import json
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


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def candidates(runs_root, scan_options, provenance, exclude=None):
    """Map entry key to the newest completed earlier OCR result with the same identity.

    ``runs_root`` holds evaluation runs (``<run>/benchmark/manifest.json``);
    ``exclude`` is the benchmark directory of the current run."""
    identity = ocr_identity(scan_options, provenance)
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
                }
                previous = found.get(row["key"])
                if (
                    previous is None
                    or candidate["finished_at"] > previous["finished_at"]
                ):
                    found[row["key"]] = candidate
    return found


def matching(rows, found):
    """The candidates whose image is byte-identical to the selected row's image."""
    return {
        row["key"]: found[row["key"]]
        for row in rows
        if row["key"] in found
        and found[row["key"]]["image_sha256"] == row["image_sha256"]
    }


def restore(candidate):
    """Copy the earlier OCR artifacts (without detection) into a new run.

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
    shutil.copytree(source, target, ignore=shutil.ignore_patterns("detection"))
    data = json.loads(result_path.read_text(encoding="utf-8"))
    data["run_id"] = run_id
    write_json(target / "result.json", data)
    return OcrResult.from_dict(
        data, artifacts=target, image=(target / "input.png").read_bytes()
    )
