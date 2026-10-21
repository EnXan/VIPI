"""Separate replayable detector artifacts; never modify saved OCR evidence."""

import json
import threading
import uuid

from .events import EventLog
from .files import write_json
from pathlib import Path


class DetectionStore(EventLog):
    def __init__(self, run_directory=None, on_event=None, *, run_id=None):
        self.id = uuid.uuid4().hex
        self.directory = (
            Path(run_directory) / "detection" / self.id
            if run_directory is not None
            else None
        )
        if self.directory is not None:
            self.directory.mkdir(parents=True)
        self.condition = threading.Condition()
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

    @classmethod
    def restore(cls, directory):
        store = cls.__new__(cls)
        store.directory = Path(directory)
        store.id = store.directory.name
        store.condition = threading.Condition()
        store.on_event = None
        store.status = json.loads((store.directory / "status.json").read_text())
        store.events = (
            [
                json.loads(x)
                for x in (store.directory / "events.jsonl").read_text().splitlines()
            ]
            if (store.directory / "events.jsonl").exists()
            else []
        )
        store.results = (
            [
                json.loads(x)
                for x in (store.directory / "answers.jsonl").read_text().splitlines()
            ]
            if (store.directory / "answers.jsonl").exists()
            else []
        )
        if store.status["state"] not in {"completed", "failed"}:
            store.emit(
                "detection_failed",
                state="failed",
                error="Server stopped before detection completed; saved answers remain available.",
            )
        return store

    def emit(self, name, **data):
        with self.condition:
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
            self.condition.notify_all()
            if self.on_event:
                self.on_event(event)

    def save_answer(self, result):
        with self.condition:
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

    def snapshot(self):
        with self.condition:
            value = {
                **self.status,
                "answers": [
                    {key: value for key, value in x.items() if key != "raw"}
                    for x in self.results
                ],
            }
            path = (
                self.directory / "result.json" if self.directory is not None else None
            )
            if path is not None and path.is_file():
                value["result"] = json.loads(path.read_text())
            return value

    def save_document(self, name, value):
        if self.directory is not None:
            write_json(self.directory / name, value)
