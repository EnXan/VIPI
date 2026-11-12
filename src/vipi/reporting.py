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
        "detections": sum(item.get("verdict") == "injection_detected" for item in files),
        "ocr_incomplete": sum(item.get("ocr_incomplete") is True for item in files),
        "failed": sum(item["status"] == "error" for item in files),
        "not_scanned": sum(item["status"] == "not_scanned" for item in files),
        "skipped": len(report["skipped"]),
    }
    # A selection-only run is complete when selection itself had no errors.
    listed = report.get("list_only", False)
    done = "selected" if listed else "completed"
    incomplete = report["errors"] or any(item["status"] != done for item in files)
    report["exit_code"] = (
        2 if incomplete else 1 if report["summary"]["detections"] else 0
    )
    report["status"] = (
        "incomplete" if incomplete else "listed" if listed else "completed"
    )
    report["elapsed_seconds"] = time.perf_counter() - started
    return report


def file_record(result):
    ocr, detection = result.ocr, result.detection
    fees = [answer.get("estimated_usd") for answer in detection.answers]
    detector_fee = (
        sum(fees)
        if fees and all(isinstance(value, (int, float)) for value in fees)
        else None
    )
    remote = [
        a
        for a in detection.answers
        if a.get("provider") in {"jev", "openai"}
    ]
    ocr_fee = ocr.cost.get("estimated_usd")
    return {
        "status": "error" if detection.errors else "completed",
        "artifacts": str(ocr.artifacts) if ocr.artifacts is not None else None,
        "run_id": ocr.run_id,
        "ocr_seconds": ocr.elapsed_seconds,
        "ocr_profile": ocr.ocr_profile,
        "ocr_passes": len(ocr.variants),
        "ocr_selection": ocr.selection,
        "ocr_cost": ocr.cost,
        "detection_cost": {
            "estimated_usd": detector_fee,
            "api_calls": len(remote),
            "http_attempts": sum(a.get("attempts", 1) for a in remote),
        },
        "estimated_total_api_cost_usd": ocr_fee + detector_fee
        if ocr_fee is not None and detector_fee is not None
        else None,
        "verdict": detection.verdict,
        "ocr_incomplete": ocr.ocr_incomplete,
        "injection_probability": detection.injection_probability,
        "threshold": detection.threshold,
        "signals": detection.signals,
        "check_id": detection.check_id,
        "detector_model": result.detector_model,
        "detector_identity": result.detector_identity,
        "detection_seconds": detection.elapsed_seconds,
        "errors": detection.errors,
    }
