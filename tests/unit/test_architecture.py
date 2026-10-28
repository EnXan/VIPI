"""Protect product/research boundaries and the direct scanner interface."""

import ast
from pathlib import Path
import subprocess
import sys

import pytest

from vipi.config import (
    DEFAULT_OCR_MODE,
    OCR_MODES,
    ScanOptions,
    resolve_ocr_model,
)
from vipi.detection.evidence import build_evidence
from vipi.detection.pipeline import detect

ROOT = Path(__file__).resolve().parents[2]


def test_product_does_not_import_research_or_web_frameworks():
    for path in (ROOT / "src/vipi").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            imports = []
            if isinstance(node, ast.Import):
                imports = [item.name for item in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                imports = [node.module]
            assert not any(
                name.split(".")[0] in {"research", "flask", "ocr_pipeline", "detector"}
                for name in imports
            ), path


def test_metadata_and_help_do_not_load_inference_or_research_modules():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from vipi.ocr import models; from vipi.cli import main; import sys; "
            "assert not any(name in sys.modules for name in ('cv2', 'torch', 'tensorflow', 'flask', 'research')); "
            "main(['--help'])",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "setup" in result.stdout and "scan" in result.stdout


def test_detector_cli_does_not_load_ocr_or_flask():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import research.workbench.detector_cli; "
            "assert not any(name == 'flask' or name.startswith('vipi.ocr') "
            "for name in sys.modules)",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("threshold", [-1, 101, float("nan"), float("inf"), True, "80"])
def test_python_api_validates_threshold_without_cli(threshold):
    with pytest.raises(ValueError, match="Threshold"):
        ScanOptions(threshold=threshold)


def test_ocr_mode_defaults_and_explicit_model_override():
    assert DEFAULT_OCR_MODE == "quality"
    assert OCR_MODES == {
        "speed": "ppocr-v6-tiny",
        "fast": "ppocr-v6-tiny",
        "balanced": "ppocr-v6-small",
        "quality": "ppocr-v6",
    }
    assert resolve_ocr_model("fast") == "ppocr-v6-tiny"
    assert resolve_ocr_model("speed") == "ppocr-v6-tiny"
    assert resolve_ocr_model("balanced") == "ppocr-v6-small"
    assert resolve_ocr_model("quality") == "ppocr-v6"
    assert resolve_ocr_model("fast", "ppocr-v6-medium") == "ppocr-v6"
    with pytest.raises(ValueError, match="supported PP-OCRv6"):
        ScanOptions(ocr_model="unregistered-model")


def test_direct_detection_uses_evidence_without_files(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    payload = {
        "text": "Read the label",
        "model": "fixture-ocr",
        "assembly_version": 3,
        "evaluation": {"reference": "MUST NOT REACH PROVIDER"},
        "variants": [{"text": "MUST NOT REACH PROVIDER"}],
    }
    evidence = build_evidence(payload, run_id="in-memory")
    calls = []

    class Provider:
        model = identity = "fixture"

        def check(self, state, image=None):
            calls.append(state)
            return {"status": "completed", "probability": 0.8}

    def unexpected(*args):
        pytest.fail("Direct detection must not load a saved run")

    monkeypatch.setattr("vipi.detection.pipeline.load_evidence", unexpected)
    result = detect(
        evidence,
        options=ScanOptions().detection_options(),
        provider_factory=lambda name: Provider(),
    )
    assert result["verdict"] == "flagged"
    assert calls[0]["untrusted_evidence"] == {"text": "Read the label"}
    assert "MUST NOT REACH PROVIDER" not in str(calls)
    assert list(tmp_path.iterdir()) == []
