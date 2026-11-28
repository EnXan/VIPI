"""Scan one uploaded image with the product scanner (OCR, then detection)."""

import json
from pathlib import Path
import tempfile
import threading
import uuid

from vipi.config import ScanOptions
from vipi.reporting import file_record

from research.ocr_eval.benchmark import CONFIGURATIONS

DEFAULT_CONFIGURATION = "local-quality-clef-flash"  # the product default (`vipi scan`)


# Report keys that hold one reading next to OCR, each with `scores` (ADR 0083-0090).
READING_REPORTS = (
    "svg",
    "metadata",
    "barcodes",
    "transparency",
    "openstego",
    "openstego_random_lsb",
    "png_lsb",
)


def options_for(configuration, threshold=None, lsb_layouts=()):
    if configuration not in CONFIGURATIONS:
        raise ValueError("Choose a supported configuration.")
    return ScanOptions(
        threshold=threshold,
        lsb_layouts=tuple(lsb_layouts),
        **CONFIGURATIONS[configuration],
    )


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
        self.reading = {}  # OCR run id -> [passes done, passes planned]
        self.checks = [0, 0]  # detection checks started, planned

    def on_event(self, event):
        self.run_id = self.run_id or event.get("run_id")
        kind = event.get("type", "")
        if kind.startswith("detection"):
            self.state = "checking"
            if kind == "detection_started":
                self.checks[1] = event.get("total") or 0
        elif kind == "check_started":
            self.checks[0] += 1
        elif event.get("run_id") and ("total" in event or "completed" in event):
            done, total = self.reading.get(event["run_id"], [0, 0])
            self.reading[event["run_id"]] = [
                event.get("completed", done),
                event.get("total", total),
            ]

    def progress(self):
        """Counts behind the scan state: OCR passes over every OCR run of the
        scan (a run can plan further passes), then detection checks."""
        runs = self.reading.values()
        return {
            "read": [sum(run[0] for run in runs), sum(run[1] for run in runs)],
            "checked": list(self.checks),
        }

    def snapshot(self):
        return {
            "id": self.id,
            "configuration": self.configuration,
            "threshold": self.threshold,
            "state": self.state,
            "result": self.result,
            "error": self.error,
            "steps": self.steps(),
            "progress": self.progress(),
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
    """Runs one scan at a time in a background thread; evaluations run
    independently (ADR 0066)."""

    def __init__(self, busy, scanner=None):
        self.busy = busy
        self.jobs = {}
        self.scanner = scanner

    def start(self, image, configuration, threshold, *, lsb_layouts=(), svg=False):
        """Scan image bytes; `svg` bytes go through a temporary .svg file,
        because VIPI recognises SVG input by its path."""
        options = options_for(configuration, threshold, lsb_layouts)
        if not self.busy.acquire(blocking=False):
            raise RuntimeError("A scan is already running.")
        job = ScanJob(configuration, threshold)
        self.jobs[job.id] = job
        threading.Thread(
            target=self.run, args=(job, image, options, svg), daemon=True
        ).start()
        return job

    def run(self, job, image, options, svg=False):
        folder = tempfile.TemporaryDirectory(prefix="vipi-workbench-") if svg else None
        try:
            if self.scanner is None:
                from vipi.scanner import scan_image as scanner
            else:
                scanner = self.scanner
            if folder:
                path = Path(folder.name) / "image.svg"
                path.write_bytes(image)
                image = path
            result = scanner(image, options=options, on_event=job.on_event)
            job.artifacts = result.ocr.artifacts
            record = file_record(result)
            job.result = {
                "verdict": record["verdict"],
                "ocr_incomplete": record["ocr_incomplete"],
                "injection_probability": record["injection_probability"],
                "threshold": record["threshold"],
                "detector": options.resolved_detector,
                "text": result.ocr.text,
                "errors": record["errors"],
                "ocr_seconds": record["ocr_seconds"],
                "detection_seconds": record["detection_seconds"],
                "cost_usd": record["estimated_total_api_cost_usd"],
                "readings": {
                    key: record[key].get("scores", {})
                    for key in READING_REPORTS
                    if isinstance(record.get(key), dict)
                },
                "image_check": record.get("image_check"),
            }
            job.state = "done"
        except Exception as error:
            job.artifacts = getattr(error, "artifacts", None)
            job.error = str(error) or type(error).__name__
            job.state = "failed"
        finally:
            if folder:
                folder.cleanup()
            self.busy.release()

    def get(self, identifier):
        if identifier not in self.jobs:
            raise KeyError(identifier)
        return self.jobs[identifier]
