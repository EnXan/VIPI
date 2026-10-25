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
    "fast": "ppocr-v6-tiny",
    "balanced": "ppocr-v6-small",
    "quality": "ppocr-v6",
}
DEFAULT_OCR_MODE = "quality"
MISTRAL_OCR_MODEL = "mistral-ocr-4-1"
OCR_MODEL_IDS = (
    *dict.fromkeys(OCR_MODES.values()),
    "ppocr-v6-medium",
    MISTRAL_OCR_MODEL,
)
# Pin the same immutable revision used by the existing local detector.
PROMPT_GUARD_REVISION = "a8ded8e697ce7c355e395a0df51f94adb4a2fd27"


def resolve_ocr_model(mode=DEFAULT_OCR_MODE, model=None):
    if mode not in OCR_MODES:
        raise ValueError("Choose the fast, balanced or quality OCR mode.")
    if model is None:
        return OCR_MODES[mode]
    if model == MISTRAL_OCR_MODEL:
        return model
    if model not in OCR_MODEL_IDS:
        raise ValueError("Choose a supported PP-OCRv6 model ID.")
    # Keep the existing model identifier used by reports and saved OCR runs.
    return "ppocr-v6" if model == "ppocr-v6-medium" else model


@dataclass(frozen=True)
class ScanOptions:
    detector: str = DEFAULT_DETECTOR
    threshold: float = DEFAULT_THRESHOLD
    ocr_mode: str = DEFAULT_OCR_MODE
    ocr_model: str | None = None

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
        resolve_ocr_model(self.ocr_mode, self.ocr_model)

    @property
    def resolved_ocr_model(self):
        return resolve_ocr_model(self.ocr_mode, self.ocr_model)

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
