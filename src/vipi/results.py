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
    assembly_version: int
    elapsed_seconds: float
    artifacts: Path | None = None
    image: bytes | None = field(default=None, repr=False)
    ocr_profile: str = "legacy-unrecorded"

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
            artifacts=artifacts,
            image=image,
        )

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
            )
        }


@dataclass(frozen=True)
class DetectionResult:
    verdict: str
    review_required: bool
    signals: dict
    answers: list[dict]
    check_id: str
    elapsed_seconds: float
    ocr_complete: bool
    missing_text_evidence: bool

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
        if not self.ocr_complete or self.missing_text_evidence:
            errors.append("No complete final OCR text evidence is available.")
        if self.verdict == "unclear" and not errors:
            errors.append("Detector evidence is incomplete; review is required.")
        return errors


@dataclass(frozen=True)
class ScanResult:
    ocr: OcrResult
    detection: DetectionResult
    detector_model: str
    detector_identity: str | dict
