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
from .recovery.pipeline import extract, PROFILE
from .recovery.decisions import DecisionsDecider, JevDecider, LocalDecider


class OcrSession:
    """Reuse a prepared OCR engine and decision provider across image scans."""

    def __init__(
        self,
        root=None,
        *,
        mode=DEFAULT_OCR_MODE,
        model=None,
        execution_mode=None,
        provider=None,
        decision_provider=None,
        decider=None,
    ):
        self.root = Path(root) if root is not None else cache_directory()
        options = ScanOptions(
            ocr_mode=mode,
            ocr_model=model,
            ocr_execution_mode=execution_mode,
            ocr_provider=provider,
            decision_provider=decision_provider,
        )
        self.mode = options.resolved_ocr_mode
        self.model = options.resolved_ocr_model
        self.execution_mode = options.resolved_ocr_execution_mode
        self.provider = options.resolved_ocr_provider
        self.decision_provider = options.resolved_decision_provider
        if decider:
            self.decider = decider
        elif self.decision_provider in {"clef", "d1"}:
            self.decider = LocalDecider(
                self.decision_provider, self.root / "decisions" / self.decision_provider
            )
        elif self.decision_provider == "jev":
            self.decider = JevDecider()
        else:
            self.decider = DecisionsDecider()
        if hasattr(self.decider, "key") and not self.decider.key:
            key = (
                "OPENAI_API_KEY"
                if self.decision_provider == "openai"
                else "TYPESAFE_API_KEY (or JEV_API_KEY)"
            )
            raise ValueError(f"Set {key} for OCR decisions before scanning.")
        if self.model in CLOUD_OCR_MODELS:
            validate_model(self.model, self.root / "ocr")
        else:
            try:
                validate_model(self.model, self.root / "ocr", verify=True)
            except ValueError as error:
                raise ValueError(
                    "OCR models are missing or invalid. Run: vipi setup"
                ) from error
        self.pool = EnginePool(
            self.model,
            self.root / "ocr",
            1,
            "cpu",
            native_pipeline=True,
        )

    @property
    def metadata(self):
        """Describe the selected OCR profile, decision model and runtime files."""
        if self.model in CLOUD_OCR_MODELS:
            return {
                "mode": self.mode,
                "execution_mode": self.execution_mode,
                "provider": self.provider,
                "model": self.model,
                "ocr_profile": PROFILE,
                "decision_provider": self.decision_provider,
                "decision_model": self.decider.model,
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
            "ocr_profile": PROFILE,
            "decision_provider": self.decision_provider,
            "decision_model": self.decider.model,
            "files": {
                FILES[key]["file"]: FILES[key]["sha256"] for key in REQUIRED[self.model]
            },
            "runtime": {name: version(name) for name in ("rapidocr", "onnxruntime")},
            "backend": "cpu",
            "workers": 1,
        }

    def extract(self, image, on_event=None):
        """Return OCR for image bytes or a path, retaining artifacts on failure."""
        store = RunStore(
            self.root / "runs", self.model, on_event, workers=1, backend="cpu"
        )
        try:
            data = extract(
                io.BytesIO(image) if isinstance(image, bytes) else image,
                self.model,
                models_dir=self.root / "ocr",
                backend="cpu",
                engine_pool=self.pool,
                store=store,
                decider=self.decider,
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
