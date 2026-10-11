"""Persistent step results and replayable progress events for one run."""

import json
import threading
import uuid
from pathlib import Path

from .runtime import DEFAULT_BACKEND, threads_per_worker


def write_json(path: Path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(path)


class RunStore:
    def __init__(
        self,
        root: Path,
        model: str,
        on_event=None,
        *,
        workers=1,
        backend=DEFAULT_BACKEND,
    ):
        self.id = uuid.uuid4().hex
        self.directory = root / self.id
        (self.directory / "images").mkdir(parents=True)
        self.condition = threading.Condition()
        self.events = []
        self.on_event = on_event
        self.status = {
            "run_id": self.id,
            "model": model,
            "state": "queued",
            "completed": 0,
            "total": 0,
            "current": None,
            "event_id": 0,
            "workers": workers,
            "backend": backend,
            "threads_per_worker": threads_per_worker(workers),
            "active_steps": {},
        }
        write_json(self.directory / "status.json", self.status)

    @classmethod
    def restore(cls, directory: Path):
        store = cls.__new__(cls)
        store.directory = directory
        store.id = directory.name
        store.condition = threading.Condition()
        store.on_event = None
        store.status = json.loads(
            (directory / "status.json").read_text(encoding="utf-8")
        )
        path = directory / "events.jsonl"
        store.events = (
            [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            if path.exists()
            else []
        )
        if store.status["state"] not in {"completed", "failed"}:
            store.status.update(
                state="failed",
                active_steps={},
                error="Server stopped before this run completed.",
            )
            store.emit(
                "run_failed",
                error=store.status["error"],
                completed=store.status["completed"],
            )
        return store

    def emit(self, name: str, **data):
        with self.condition:
            event = {
                "id": len(self.events) + 1,
                "type": name,
                "run_id": self.id,
                **data,
            }
            with (self.directory / "events.jsonl").open("a", encoding="utf-8") as file:
                file.write(json.dumps(event, ensure_ascii=False) + "\n")
                file.flush()
            self.events.append(event)
            self.status["event_id"] = event["id"]
            write_json(self.directory / "status.json", self.status)
            self.condition.notify_all()
            if self.on_event:
                self.on_event(event)

    def transition(self, name, *, data=None, **updates):
        with self.condition:
            self.status.update(updates)
            self.emit(
                name,
                **{key: value for key, value in updates.items() if key != "state"},
                **(data or {}),
            )

    def advance(self, worker_id, name, state, step):
        with self.condition:
            self.status["state"] = "processing" if self.status["workers"] > 1 else state
            self.status["current"] = step
            self.status["active_steps"][str(worker_id)] = {"state": state, "step": step}
            self.emit(name, worker_id=worker_id, step=step)

    def complete_step(self, worker_id, step):
        with self.condition:
            self.save_step(step)
            self.status["completed"] += 1
            self.status["current"] = step
            self.status["active_steps"].pop(str(worker_id), None)
            self.emit(
                "step_completed",
                worker_id=worker_id,
                step=step,
                completed=self.status["completed"],
            )

    def save_step(self, step):
        with self.condition:
            with (self.directory / "steps.jsonl").open("a", encoding="utf-8") as file:
                file.write(json.dumps(step, ensure_ascii=False) + "\n")
                file.flush()

    def snapshot(self):
        with self.condition:
            status = {
                **self.status,
                "active_steps": dict(self.status.get("active_steps", {})),
            }
            steps = self.directory / "steps.jsonl"
            status["variants"] = (
                [
                    json.loads(line)
                    for line in steps.read_text(encoding="utf-8").splitlines()
                ]
                if steps.exists()
                else []
            )
            result = self.directory / "result.json"
            status["variants"].sort(key=lambda step: step.get("index", int(step["id"])))
            if status["state"] == "completed":
                status["result"] = json.loads(result.read_text(encoding="utf-8"))
            return status

    def stream(self, after: int = 0):
        while True:
            with self.condition:
                batch = self.events[after:]
                terminal = self.status["state"] in {"completed", "failed"}
                if not batch and not terminal:
                    self.condition.wait(timeout=15)
                    batch = self.events[after:]
                    terminal = self.status["state"] in {"completed", "failed"}
            for event in batch:
                yield f"id: {event['id']}\nevent: {event['type']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
                after = event["id"]
            if terminal:
                return
            if not batch:
                yield ": keepalive\n\n"
