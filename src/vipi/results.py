"""Typed boundaries between OCR, detection and scanner adapters."""

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class OcrResult:
    run_id: str
    model: str
    text: str
    regions: list[dict]
    variants: list[dict]
    input_size: list[int]
    assembly_version: int | str | None
    elapsed_seconds: float
    artifacts: Path | None = None
    image: bytes | None = field(default=None, repr=False)
    ocr_profile: str = "legacy-unrecorded"
    selection: dict = field(default_factory=dict)
    cost: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data, *, artifacts=None, image=None):
        return cls(
            **{
                name: data[name]
                for name in (
                    "run_id",
                    "model",
                    "text",
                    "regions",
                    "variants",
                    "input_size",
                    "assembly_version",
                    "elapsed_seconds",
                )
            },
            ocr_profile=data.get("ocr_profile", "legacy-unrecorded"),
            selection=data.get("selection", {}),
            cost=data.get("cost", {}),
            artifacts=artifacts,
            image=image,
        )

    @property
    def ocr_incomplete(self):
        """Whether readable text is missing from the final text; None if not judged."""
        return self.selection.get("ocr_incomplete")

    def to_dict(self):
        return {
            name: getattr(self, name)
            for name in (
                "run_id",
                "model",
                "ocr_profile",
                "text",
                "regions",
                "variants",
                "input_size",
                "assembly_version",
                "elapsed_seconds",
                "selection",
                "cost",
            )
        }


@dataclass(frozen=True)
class DetectionResult:
    verdict: str | None
    injection_probability: float | None
    threshold: float | None
    signals: dict
    answers: list[dict]
    check_id: str
    elapsed_seconds: float
    ocr_complete: bool

    @classmethod
    def from_dict(cls, data):
        return cls(**{name: data[name] for name in cls.__dataclass_fields__})

    @property
    def errors(self):
        errors = [
            answer.get("error", "Detector check did not complete.")
            for answer in self.answers
            if answer["status"] != "completed"
        ]
        if not self.ocr_complete:
            errors.append("The final OCR text is not available.")
        if self.verdict is None and not errors:
            errors.append("The detector produced no verdict (no threshold set).")
        return errors


@dataclass(frozen=True)
class ScanResult:
    ocr: OcrResult
    detection: DetectionResult
    detector_model: str
    detector_identity: str | dict
