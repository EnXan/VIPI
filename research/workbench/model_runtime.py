"""Keep a heavy OCR backend in its own interpreter for one sequential model run."""

from concurrent.futures import CancelledError
import json
import os
from pathlib import Path
import subprocess
import tempfile
import uuid

from .model_registry import ROOT, interpreter_for

PREFIX = "VIPI_OCR_RESULT "


class ModelInitializationError(RuntimeError):
    pass


class WorkerEngine:
    def __init__(self, model, directory, *, profile, backend, threads):
        directory = Path(directory).resolve()
        self.temporary = tempfile.TemporaryDirectory(prefix="vipi-model-")
        logs = directory / "runtime-logs"
        logs.mkdir(parents=True, exist_ok=True)
        self.log_path = logs / f"{model}-{uuid.uuid4().hex}.log"
        self.log = self.log_path.open("w", encoding="utf-8")
        self.cancelled = False
        self.ready = False
        self.initialization_seconds = 0
        self.process = subprocess.Popen(
            [
                interpreter_for(model),
                "-m",
                "research.workbench.model_worker",
                "--model",
                model,
                "--models-dir",
                str(directory),
                "--profile",
                profile,
                "--backend",
                backend,
                "--threads",
                str(threads),
            ],
            cwd=ROOT,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self.log,
            text=True,
            env={
                **os.environ,
                "PYTHONUNBUFFERED": "1",
                "PYTHONPATH": str(ROOT) + os.pathsep + os.environ.get("PYTHONPATH", ""),
            },
        )

    def _read(self):
        while True:
            line = self.process.stdout.readline()
            if self.cancelled:
                raise CancelledError()
            if not line:
                error = (
                    f"OCR runtime exited ({self.process.poll()}); see {self.log_path}"
                )
                raise (
                    RuntimeError(error)
                    if self.ready
                    else ModelInitializationError(error)
                )
            if line.startswith(PREFIX):
                return json.loads(line[len(PREFIX) :])
            self.log.write(line)
            self.log.flush()

    def recognize(self, image):
        if not self.ready:
            answer = self._read()
            if answer.get("error"):
                raise ModelInitializationError(answer["error"])
            self.ready = True
            self.initialization_seconds = answer["initialization_seconds"]
        source, target = (
            Path(self.temporary.name) / "input.png",
            Path(self.temporary.name) / "output.json",
        )
        image.save(source, format="PNG")
        self.process.stdin.write(
            json.dumps({"image": str(source), "output": str(target)}) + "\n"
        )
        self.process.stdin.flush()
        answer = self._read()
        if answer.get("error"):
            raise RuntimeError(answer["error"])
        result = json.loads(target.read_text(encoding="utf-8"))
        result.setdefault("preprocessing", {}).update(
            runtime_initialization_seconds=self.initialization_seconds,
            runtime_inference_seconds=answer["inference_seconds"],
            runtime_log=str(self.log_path),
        )
        self.initialization_seconds = 0
        return result

    def cancel(self):
        self.cancelled = True
        if self.process.poll() is None:
            self.process.kill()

    def close(self):
        if self.process.poll() is None:
            self.process.kill()
        self.process.wait()
        for stream in (self.process.stdin, self.process.stdout, self.log):
            stream.close()
        self.temporary.cleanup()
