"""Own OCR resources and artifact details behind a reusable session."""

from importlib.metadata import version
import io
from pathlib import Path

from vipi.config import (
    DEFAULT_OCR_MODE,
    MISTRAL_OCR_MODEL,
    api_key,
    cache_directory,
    resolve_ocr_model,
)
from vipi.results import OcrResult
from vipi.storage.ocr import RunStore
from .engine_pool import EnginePool
from .models import FILES, REQUIRED, validate_model
from .pipeline import extract
from .transforms import MISTRAL_OCR_PROFILE, OCR_PROFILE


class OcrSession:
    def __init__(self, root=None, *, mode=DEFAULT_OCR_MODE, model=None):
        self.root = Path(root) if root is not None else cache_directory()
        self.mode = mode
        self.model = resolve_ocr_model(mode, model)
        if self.model == MISTRAL_OCR_MODEL and not api_key("MISTRAL_API_KEY"):
            raise ValueError(
                "Mistral OCR requires MISTRAL_API_KEY. Set it in the environment or .env."
            )
        if self.model != MISTRAL_OCR_MODEL:
            try:
                validate_model(self.model, self.root / "ocr", verify=True)
            except ValueError as error:
                raise ValueError(
                    "OCR models are missing or invalid. Run: vipi setup"
                ) from error
        self.pool = EnginePool(self.model, self.root / "ocr", 1, "cpu")

    @property
    def metadata(self):
        if self.model == MISTRAL_OCR_MODEL:
            return {
                "mode": self.mode,
                "model": self.model,
                "ocr_profile": MISTRAL_OCR_PROFILE,
                "files": {},
                "runtime": {},
                "backend": "api",
                "workers": 1,
            }
        return {
            "mode": self.mode,
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
