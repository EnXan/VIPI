"""Run one detector on the final OCR text retained by an earlier evaluation run.

No OCR runs: each image's OCR result is restored from the source run, so every
detector sees the same text (ADR 0074). Results are kept apart from the saved
end-to-end baselines and written to ``runs/detector-text/<run>/``.
"""

from datetime import datetime, timezone
import json
from pathlib import Path
import statistics
import time

from vipi.config import DEFAULT_THRESHOLD, DETECTOR_THRESHOLDS, cache_directory
from vipi.detection.pipeline import detect_ocr, settings
from vipi.detection.providers import prepare_provider
from vipi.results import ScanResult
from vipi.storage.files import write_json

from research.ocr_eval import benchmark, benchmark_report, ocr_reuse

from .runs import DEFAULT_RUNS_DIRECTORY

DEFAULT_OUTPUT_DIRECTORY = Path("runs/detector-text")
DETECTORS = ("prompt-guard", "d1", "clef-flash", "jev", "openai")


def source_rows(directory):
    """Rows of a complete source run, with their dataset labels."""
    report = json.loads((directory / "report.json").read_text(encoding="utf-8"))
    if not report["inference_complete"]:
        raise ValueError(f"Source run {directory.name} is not complete.")
    (configuration,) = report["configurations"]
    retained = directory / "benchmark" / configuration / "rows"
    rows = []
    for scored in report["configurations"][configuration]["rows"]:
        row = json.loads(
            (retained / f"{scored['key'].replace(':', '-')}.json").read_text(
                encoding="utf-8"
            )
        )
        rows.append({**row, "label": scored["label"]})
    return configuration, rows


def input_texts(artifacts):
    """The OCR readings the newest detector check of one image inspected.

    Readings, not detector jobs: providers split long text into differently
    sized jobs, so the same text can arrive in a different number of jobs."""
    found = sorted(
        Path(artifacts).glob("detection/*/inputs.json"),
        key=lambda path: path.stat().st_mtime,
    )
    if not found:
        return None
    inputs = json.loads(found[-1].read_text(encoding="utf-8"))
    return [reading["text"] for reading in inputs["evidence"]["readings"]]


def finished(record):
    """A row that need not run again: detection completed without errors."""
    return record["status"] == "completed" and not record["detection"]["errors"]


def detect_row(row, detector, options, provider):
    """Restore the source OCR and run only detection; record what it saw."""
    record = {
        "key": row["key"],
        "label": row["label"],
        "source_artifacts": row.get("artifacts"),
    }
    if row["status"] != "completed":
        return {**record, "status": "source_failed"}
    ocr = ocr_reuse.restore(
        {"artifacts": row["artifacts"], "result_sha256": row["result_sha256"]}
    )
    if ocr is None:
        return {
            **record,
            "status": "failed",
            "error": "Source artifacts are missing or changed.",
        }
    started = time.perf_counter()
    try:
        detection = detect_ocr(
            ocr, options=options, provider_factory=lambda name: provider
        )
    except Exception as error:
        return {
            **record,
            "status": "failed",
            "error_type": type(error).__name__,
            "error": str(error),
        }
    result = ScanResult(ocr, detection, provider.model, provider.identity)
    scanned = benchmark.scanned_record(result, None)
    texts = input_texts(ocr.artifacts)
    return {
        **record,
        "status": "completed",
        "artifacts": scanned["artifacts"],
        "detection": scanned["detection"],
        "seconds": time.perf_counter() - started,
        "same_text_as_source": texts == input_texts(row["artifacts"]),
    }


def summarize(rows):
    seconds = [
        row["detection"]["seconds"]
        for row in rows
        if row.get("detection") and row["detection"]["seconds"] is not None
    ]
    return {
        "images": len(rows),
        "same_text_as_source": sum(
            row.get("same_text_as_source") is True for row in rows
        ),
        "text_differs": sum(row.get("same_text_as_source") is False for row in rows),
        # Source failures stay as they are; every other unfinished row runs
        # again on resume.
        "failed": sum(not finished(row) for row in rows),
        "detection": benchmark_report.detection_summary(rows),
        "median_detection_seconds": statistics.median(seconds) if seconds else None,
        "mean_detection_seconds": statistics.mean(seconds) if seconds else None,
    }


def run(
    source_run,
    detector,
    *,
    runs_directory=DEFAULT_RUNS_DIRECTORY,
    output_directory=DEFAULT_OUTPUT_DIRECTORY,
    threshold=None,
):
    """Detect on every image of ``source_run``; resumes an unfinished run."""
    if detector not in DETECTORS:
        raise ValueError(f"Choose one of: {', '.join(DETECTORS)}.")
    if threshold is None:
        threshold = DETECTOR_THRESHOLDS.get(detector, DEFAULT_THRESHOLD)
    source = Path(runs_directory) / source_run
    configuration, rows = source_rows(source)
    target = Path(output_directory) / f"{source_run}--{detector}"
    (target / "rows").mkdir(parents=True, exist_ok=True)
    request = {
        "source_run": source_run,
        "source_configuration": configuration,
        "detector": detector,
        "threshold": threshold,
        "provenance": benchmark.provenance(),
    }
    request_path = target / "request.json"
    if request_path.exists():
        recorded = json.loads(request_path.read_text(encoding="utf-8"))
        if {k: recorded[k] for k in ("source_run", "detector", "threshold")} != {
            k: request[k] for k in ("source_run", "detector", "threshold")
        }:
            raise ValueError(f"{target} holds a different request.")
    else:
        write_json(
            request_path,
            {**request, "started_at": datetime.now(timezone.utc).isoformat()},
        )
    options = settings(
        text_classifier=detector,
        thresholds={
            "version": "vipi-cli-score-v1",
            "signals": {detector: {"threshold": threshold / 100}},
        },
    )
    provider = prepare_provider(detector, cache_directory() / "prompt-guard")
    records = []
    for row in rows:
        path = target / "rows" / f"{row['key'].replace(':', '-')}.json"
        if path.exists():
            earlier = json.loads(path.read_text(encoding="utf-8"))
            if finished(earlier) or earlier["status"] == "source_failed":
                records.append(earlier)
                continue
        record = detect_row(row, detector, options, provider)
        write_json(path, record)
        records.append(record)
        print(f"{detector} {row['key']} {record['status']}", flush=True)
    summary = {**request, "summary": summarize(records)}
    write_json(target / "summary.json", summary)
    return target, summary
