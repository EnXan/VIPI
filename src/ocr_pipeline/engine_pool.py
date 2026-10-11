"""Keep one OCR instance per executor thread for a complete image batch."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import threading

from .engines import create_engine
from .runtime import threads_per_worker, validate_backend
from .workers import worker_count


class EnginePool:
    def __init__(self, model, directory, workers, backend, engine_factory=None):
        validate_backend(model, backend)
        self.model = model
        self.directory = Path(directory).resolve()
        self.workers = worker_count(workers)
        self.backend = backend
        self.factory = engine_factory
        self.local = threading.local()
        self.executor = ThreadPoolExecutor(
            max_workers=self.workers, thread_name_prefix="ocr"
        )

    def engine(self):
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
        return self.local.engine

    def discard_engine(self):
        if hasattr(self.local, "engine"):
            del self.local.engine

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.executor.shutdown(wait=True, cancel_futures=True)
