"""Own OCR resources and artifact details behind a reusable session."""

from importlib.metadata import version
import io
from pathlib import Path

from vipi.config import (
    DEFAULT_OCR_MODE,
    CLOUD_OCR_MODELS,
    ScanOptions,
    cache_directory,
)
from vipi.results import OcrResult
from vipi.storage.ocr import RunStore
from .engine_pool import EnginePool
from .models import FILES, REQUIRED, validate_model
from .pipeline import extract
from .transforms import CLOUD_OCR_PROFILES, OCR_PROFILE


class OcrSession:
    def __init__(
        self,
        root=None,
        *,
        mode=DEFAULT_OCR_MODE,
        model=None,
        execution_mode=None,
        provider=None,
    ):
        self.root = Path(root) if root is not None else cache_directory()
        options = ScanOptions(
            ocr_mode=mode,
            ocr_model=model,
            ocr_execution_mode=execution_mode,
            ocr_provider=provider,
        )
        self.mode = options.resolved_ocr_mode
        self.model = options.resolved_ocr_model
        self.execution_mode = options.resolved_ocr_execution_mode
        self.provider = options.resolved_ocr_provider
        if self.model in CLOUD_OCR_MODELS:
            validate_model(self.model, self.root / "ocr")
        else:
            try:
                validate_model(self.model, self.root / "ocr", verify=True)
            except ValueError as error:
                raise ValueError(
                    "OCR models are missing or invalid. Run: vipi setup"
                ) from error
        self.pool = EnginePool(self.model, self.root / "ocr", 1, "cpu")

    @property
    def metadata(self):
        if self.model in CLOUD_OCR_MODELS:
            return {
                "mode": self.mode,
                "execution_mode": self.execution_mode,
                "provider": self.provider,
                "model": self.model,
                "ocr_profile": CLOUD_OCR_PROFILES[self.model],
                "files": {},
                "runtime": {},
                "backend": "api",
                "workers": 1,
            }
        return {
            "mode": self.mode,
            "execution_mode": self.execution_mode,
            "provider": self.provider,
            "model": self.model,
            "ocr_profile": OCR_PROFILE,
            "files": {
                FILES[key]["file"]: FILES[key]["sha256"] for key in REQUIRED[self.model]
            },
            "runtime": {name: version(name) for name in ("rapidocr", "onnxruntime")},
            "backend": "cpu",
            "workers": 1,
        }

    def extract(self, image, on_event=None):
        store = RunStore(
            self.root / "runs", self.model, on_event, workers=1, backend="cpu"
        )
        try:
            data = extract(
                io.BytesIO(image) if isinstance(image, bytes) else image,
                self.model,
                models_dir=self.root / "ocr",
                workers=1,
                backend="cpu",
                engine_pool=self.pool,
                store=store,
            )
        except (Exception, KeyboardInterrupt) as error:
            error.artifacts = store.directory
            raise
        return OcrResult.from_dict(
            data,
            artifacts=store.directory,
            image=(store.directory / "input.png").read_bytes(),
        )

    def __enter__(self):
        self.pool.__enter__()
        return self

    def __exit__(self, *exc):
        self.pool.__exit__(*exc)
