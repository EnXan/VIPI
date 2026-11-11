"""Persist detector checks separately from the final OCR evidence."""

import json
import threading
import uuid

from .files import write_json
from pathlib import Path


class DetectionStore:
    def __init__(self, run_directory=None, on_event=None, *, run_id=None):
        self.id = uuid.uuid4().hex
        self.directory = (
            Path(run_directory) / "detection" / self.id
            if run_directory is not None
            else None
        )
        if self.directory is not None:
            self.directory.mkdir(parents=True)
        self.lock = threading.RLock()
        self.on_event = on_event
        self.events = []
        self.results = []
        self.status = {
            "check_id": self.id,
            "run_id": Path(run_directory).name if run_directory is not None else run_id,
            "state": "queued",
            "completed": 0,
            "total": 0,
            "event_id": 0,
        }
        self.save_document("status.json", self.status)

    def emit(self, name, **data):
        with self.lock:
            self.status.update(data)
            event = {"id": len(self.events) + 1, "type": name, **self.status}
            if self.directory is not None:
                with (self.directory / "events.jsonl").open(
                    "a", encoding="utf-8"
                ) as file:
                    file.write(
                        json.dumps(event, ensure_ascii=False, allow_nan=False) + "\n"
                    )
            self.events.append(event)
            self.status["event_id"] = event["id"]
            self.save_document("status.json", self.status)
            if self.on_event:
                self.on_event(event)

    def save_answer(self, result):
        with self.lock:
            if self.directory is not None:
                with (self.directory / "answers.jsonl").open(
                    "a", encoding="utf-8"
                ) as file:
                    file.write(
                        json.dumps(result, ensure_ascii=False, allow_nan=False) + "\n"
                    )
            self.results.append(result)
            self.emit(
                "check_completed",
                completed=len(self.results),
                answer={key: value for key, value in result.items() if key != "raw"},
            )

    def save_document(self, name, value):
        if self.directory is not None:
            write_json(self.directory / name, value)
