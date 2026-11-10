"""Reuse a stateful OCR engine per calling thread across an image batch."""

from pathlib import Path
import threading

from .engines import create_engine
from .types import OcrEngine
from .runtime import threads_per_worker, validate_backend
from .workers import worker_count


class EnginePool:
    """Own and release the engines used by a scan batch."""

    def __init__(
        self,
        model,
        directory,
        workers,
        backend,
        engine_factory=None,
    ):
        validate_backend(model, backend)
        self.model = model
        self.directory = Path(directory).resolve()
        self.workers = worker_count(workers)
        self.backend = backend
        self.factory = engine_factory
        self.local = threading.local()
        self.engines = []
        self.lock = threading.Lock()
        self.cancelled = False

    def engine(self) -> OcrEngine:
        if not hasattr(self.local, "engine"):
            self.local.engine = (
                self.factory(self.model, self.directory)
                if self.factory is not None
                else create_engine(
                    self.model,
                    self.directory,
                    backend=self.backend,
                    threads=threads_per_worker(self.workers),
                )
            )
            with self.lock:
                self.engines.append(self.local.engine)
                cancelled = self.cancelled
            if cancelled and hasattr(self.local.engine, "cancel"):
                self.local.engine.cancel()
        return self.local.engine

    def discard_engine(self):
        if hasattr(self.local, "engine"):
            engine = self.local.engine
            if hasattr(engine, "close"):
                engine.close()
            with self.lock:
                self.engines.remove(engine)
            del self.local.engine

    def cancel(self):
        with self.lock:
            self.cancelled = True
            engines = list(self.engines)
        for engine in engines:
            if hasattr(engine, "cancel"):
                engine.cancel()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        for engine in self.engines:
            if hasattr(engine, "close"):
                engine.close()
        self.engines.clear()
