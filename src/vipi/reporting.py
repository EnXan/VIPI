"""Public report conversion and CLI exit policy."""

import os
from pathlib import Path
import time
from .storage.files import write_json as write_report

__all__ = ["write_report", "report_overwrites_input", "finish", "file_record"]


def report_overwrites_input(output, paths):
    if output is None:
        return False
    targets = {Path(os.path.abspath(output)), Path(output).resolve()}
    return any(path in targets for path in paths)


def finish(report, started):
    files = report["files"]
    report["summary"] = {
        "selected": len(files),
        "completed": sum(item["status"] == "completed" for item in files),
        "detections": sum(item.get("verdict") == "flagged" for item in files),
        "failed": sum(item["status"] == "error" for item in files),
        "not_scanned": sum(item["status"] == "not_scanned" for item in files),
        "skipped": len(report["skipped"]),
    }
    incomplete = report["errors"] or any(
        item["status"] != "completed" for item in files
    )
    report["exit_code"] = (
        2 if incomplete else 1 if report["summary"]["detections"] else 0
    )
    report["status"] = "incomplete" if incomplete else "completed"
    report["elapsed_seconds"] = time.perf_counter() - started
    return report


def file_record(result):
    ocr, detection = result.ocr, result.detection
    return {
        "status": "error" if detection.errors else "completed",
        "artifacts": str(ocr.artifacts) if ocr.artifacts is not None else None,
        "run_id": ocr.run_id,
        "ocr_seconds": ocr.elapsed_seconds,
        "ocr_profile": ocr.ocr_profile,
        "ocr_passes": len(ocr.variants),
        "verdict": detection.verdict,
        "review_required": detection.review_required,
        "signals": detection.signals,
        "check_id": detection.check_id,
        "detector_model": result.detector_model,
        "detector_identity": result.detector_identity,
        "detection_seconds": detection.elapsed_seconds,
        "errors": detection.errors,
    }
