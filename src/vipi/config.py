"""Release defaults; OCR adapters remain owned by vipi.ocr.engines."""

import os
import sys
import math
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values

DETECTORS = ("jev", "openai", "prompt-guard")
DEFAULT_DETECTOR = "jev"
DEFAULT_THRESHOLD = 80
OCR_MODES = {
    "speed": "ppocr-v6-tiny",
    "balanced": "ppocr-v6-small",
    "quality": "ppocr-v6",
    "fast": "ppocr-v6-tiny",  # Compatibility alias for the original CLI.
}
DEFAULT_OCR_MODE = "quality"
MISTRAL_OCR_MODEL = "mistral-ocr-4-1"
GOOGLE_OCR_MODEL = "google-cloud-vision"
LUNA_OCR_MODEL = "gpt-6-luna"
OCR_EXECUTION_MODES = ("local", "cloud")
DEFAULT_OCR_EXECUTION_MODE = "local"
CLOUD_OCR_PROVIDERS = {
    "google": GOOGLE_OCR_MODEL,
    "openai": LUNA_OCR_MODEL,
    "mistral": MISTRAL_OCR_MODEL,
}
DEFAULT_OCR_PROVIDER = "google"
CLOUD_OCR_MODELS = tuple(CLOUD_OCR_PROVIDERS.values())
OCR_API_KEY_NAMES = {
    GOOGLE_OCR_MODEL: ("GOOGLE_CLOUD_API_KEY", "GOOGLE_API_KEY"),
    LUNA_OCR_MODEL: ("OPENAI_API_KEY",),
    MISTRAL_OCR_MODEL: ("MISTRAL_API_KEY",),
}
PADDLEOCR_VL_MODEL = "paddleocr-vl-1.6"
GRANITE_DOCLING_MODEL = "granite-docling-258m"
WORKBENCH_OCR_MODELS = (PADDLEOCR_VL_MODEL, GRANITE_DOCLING_MODEL)
OCR_MODEL_IDS = (
    *dict.fromkeys(OCR_MODES.values()),
    "ppocr-v6-medium",
    *CLOUD_OCR_MODELS,
)
# Pin the same immutable revision used by the existing local detector.
PROMPT_GUARD_REVISION = "a8ded8e697ce7c355e395a0df51f94adb4a2fd27"


def resolve_ocr_model(
    mode=DEFAULT_OCR_MODE, model=None, *, execution_mode=None, provider=None
):
    if mode not in OCR_MODES:
        raise ValueError(
            "Choose the speed, balanced or quality OCR mode (fast is a legacy alias)."
        )
    if execution_mode not in (None, *OCR_EXECUTION_MODES):
        raise ValueError("Choose the local or cloud execution mode.")
    if model is not None and model not in OCR_MODEL_IDS:
        raise ValueError("Choose a supported PP-OCRv6 or cloud OCR model ID.")
    if provider is not None:
        if provider not in CLOUD_OCR_PROVIDERS:
            raise ValueError("Choose the google, openai or mistral OCR provider.")
        if execution_mode != "cloud":
            raise ValueError("--ocr-provider requires --modus cloud.")
        if model is not None:
            raise ValueError("Choose --ocr-provider or --ocr-model, not both.")
    selected_mode = execution_mode or (
        "cloud" if model in CLOUD_OCR_MODELS else DEFAULT_OCR_EXECUTION_MODE
    )
    if model is None:
        return (
            CLOUD_OCR_PROVIDERS[provider or DEFAULT_OCR_PROVIDER]
            if selected_mode == "cloud"
            else OCR_MODES[mode]
        )
    if (model in CLOUD_OCR_MODELS) != (selected_mode == "cloud"):
        raise ValueError(
            "The selected OCR model conflicts with --modus. Choose a model for that execution mode."
        )
    # Keep the existing model identifier used by reports and saved OCR runs.
    return "ppocr-v6" if model == "ppocr-v6-medium" else model


@dataclass(frozen=True)
class ScanOptions:
    detector: str = DEFAULT_DETECTOR
    threshold: float = DEFAULT_THRESHOLD
    ocr_mode: str = DEFAULT_OCR_MODE
    ocr_model: str | None = None
    ocr_execution_mode: str | None = None
    ocr_provider: str | None = None

    def __post_init__(self):
        if self.detector not in DETECTORS:
            raise ValueError("Choose a supported detector.")
        if (
            isinstance(self.threshold, bool)
            or not isinstance(self.threshold, (int, float))
            or not math.isfinite(self.threshold)
            or not 0 <= self.threshold <= 100
        ):
            raise ValueError("Threshold must be a number between 0 and 100.")
        self.resolved_ocr_model

    @property
    def resolved_ocr_model(self):
        return resolve_ocr_model(
            self.ocr_mode,
            self.ocr_model,
            execution_mode=self.ocr_execution_mode,
            provider=self.ocr_provider,
        )

    @property
    def resolved_ocr_execution_mode(self):
        return "cloud" if self.resolved_ocr_model in CLOUD_OCR_MODELS else "local"

    @property
    def resolved_ocr_provider(self):
        return next(
            (
                name
                for name, model in CLOUD_OCR_PROVIDERS.items()
                if model == self.resolved_ocr_model
            ),
            None,
        )

    @property
    def resolved_ocr_mode(self):
        return self.ocr_mode if self.resolved_ocr_execution_mode == "local" else None

    def detection_options(self):
        from .detection.pipeline import settings

        return settings(
            text_classifier=self.detector,
            thresholds={
                "version": "vipi-cli-score-v1",
                "signals": {self.detector: {"threshold": self.threshold / 100}},
            },
        )


def cache_directory():
    if os.environ.get("XDG_CACHE_HOME"):
        base = Path(os.environ["XDG_CACHE_HOME"])
    elif sys.platform == "darwin":
        base = Path.home() / "Library/Caches"
    elif sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
    else:
        base = Path.home() / ".cache"
    return base.resolve() / "vipi"


def api_key(*names: str) -> str | None:
    # Check all environment aliases before consulting the file. An explicitly
    # empty environment setting disables the file fallback for this provider.
    if any(name in os.environ for name in names):
        return next((os.environ[name] for name in names if os.environ.get(name)), None)
    values = dotenv_values(Path.cwd() / ".env")
    return next((values[name] for name in names if values.get(name)), None)
