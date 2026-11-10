"""Scan one uploaded image with the product scanner (OCR, then detection)."""

import json
from pathlib import Path
import threading
import uuid

from vipi.config import DEFAULT_THRESHOLD, ScanOptions
from vipi.reporting import file_record

from research.ocr_eval.benchmark import CONFIGURATIONS

DEFAULT_CONFIGURATION = "local-quality-clef-flash"  # the product default (`vipi scan`)


def options_for(configuration, threshold=DEFAULT_THRESHOLD):
    if configuration not in CONFIGURATIONS:
        raise ValueError("Choose a supported configuration.")
    return ScanOptions(threshold=threshold, **CONFIGURATIONS[configuration])


class ScanJob:
    def __init__(self, configuration, threshold):
        self.id = uuid.uuid4().hex
        self.configuration = configuration
        self.threshold = threshold
        self.state = "reading"  # reading -> checking -> done | failed
        self.run_id = None
        self.artifacts = None
        self.result = None
        self.error = None

    def on_event(self, event):
        self.run_id = self.run_id or event.get("run_id")
        if event.get("type", "").startswith("detection"):
            self.state = "checking"

    def snapshot(self):
        return {
            "id": self.id,
            "configuration": self.configuration,
            "threshold": self.threshold,
            "state": self.state,
            "result": self.result,
            "error": self.error,
            "steps": self.steps(),
        }

    def steps(self):
        """The OCR passes (image variant and text) recorded for this scan."""
        if self.artifacts is None:
            return []
        path = Path(self.artifacts) / "steps.jsonl"
        if not path.is_file():
            return []
        steps = [json.loads(line) for line in path.read_text().splitlines() if line]
        return [
            {
                "id": step["id"],
                "label": step.get("label") or step["id"],
                "text": step.get("text", ""),
                "image_url": f"/api/scans/{self.id}/steps/{step['id']}.png",
            }
            for step in steps
        ]

    def step_image(self, step_id):
        if self.artifacts is None or not step_id.isdigit():
            raise ValueError("Step image not found.")
        path = Path(self.artifacts) / "images" / f"{step_id}.png"
        if not path.is_file():
            raise ValueError("Step image not found.")
        return path


class ScanService:
    """Runs one scan at a time in a background thread; ``busy`` is shared with
    evaluations so that only one model workload runs."""

    def __init__(self, busy, scanner=None):
        self.busy = busy
        self.jobs = {}
        self.scanner = scanner

    def start(self, image, configuration, threshold):
        options = options_for(configuration, threshold)
        if not self.busy.acquire(blocking=False):
            raise RuntimeError("A scan or evaluation is already running.")
        job = ScanJob(configuration, threshold)
        self.jobs[job.id] = job
        threading.Thread(
            target=self.run, args=(job, image, options), daemon=True
        ).start()
        return job

    def run(self, job, image, options):
        try:
            if self.scanner is None:
                from vipi.scanner import scan_image as scanner
            else:
                scanner = self.scanner
            result = scanner(image, options=options, on_event=job.on_event)
            job.artifacts = result.ocr.artifacts
            record = file_record(result)
            job.result = {
                "verdict": record["verdict"],
                "score": (record["signals"].get(options.resolved_detector) or {}).get(
                    "max_score"
                ),
                "detector": options.resolved_detector,
                "text": result.ocr.text,
                "errors": record["errors"],
                "ocr_seconds": record["ocr_seconds"],
                "detection_seconds": record["detection_seconds"],
                "cost_usd": record["estimated_total_api_cost_usd"],
            }
            job.state = "done"
        except Exception as error:
            job.artifacts = getattr(error, "artifacts", None)
            job.error = str(error) or type(error).__name__
            job.state = "failed"
        finally:
            self.busy.release()

    def get(self, identifier):
        if identifier not in self.jobs:
            raise KeyError(identifier)
        return self.jobs[identifier]
