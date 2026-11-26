"""Transparency views through a full scan with fake OCR and detector (ADR 0085).

The fake OCR engine reads a case's text only from a raster that shows it, that
is with a text-to-background contrast of at least ``VISIBLE_CONTRAST``. An attack
is therefore detected only when a view that shows its text is scanned.
"""

import json

import numpy as np
import pytest

from tests.transparency_cases import (
    CASES,
    PAYLOAD,
    VISIBLE_CONTRAST,
    opaque_rgba,
    text_mask,
)
from vipi.scanner import scan

SCORE = 0.9


def shows_text(raster):
    gray = np.asarray(raster.convert("L")).astype(float)
    mask = text_mask()
    if gray.shape != mask.shape:  # an upscaled or tiled recovery probe
        return False
    return abs(gray[mask].mean() - gray[~mask].mean()) >= VISIBLE_CONTRAST


@pytest.fixture
def visible_text(scanner_runtime, monkeypatch):
    """Set ``visible_text.text`` to what the fake OCR reads from a showing raster."""
    provider, _ = scanner_runtime

    class State:
        text = ""

    class Engine:
        def recognize(self, raster):
            if not shows_text(raster):
                return {"text": "", "regions": []}
            return {
                "text": State.text,
                "regions": [
                    {
                        "text": State.text,
                        "polygon": [[16, 20], [380, 20], [380, 56], [16, 56]],
                        "confidence": 0.99,
                    }
                ],
            }

    monkeypatch.setattr(
        "vipi.ocr.engine_pool.create_engine", lambda *args, **kwargs: Engine()
    )

    def check(payload, image=None):
        provider.calls.append(payload)
        found = PAYLOAD in json.dumps(payload, ensure_ascii=False)
        return {"status": "completed", "probability": SCORE if found else 0.0}

    provider.check = check
    return State


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.id)
def test_scan(case, tmp_path, visible_text):
    visible_text.text = case.text
    path = tmp_path / f"{case.id}.{case.format.lower()}"
    path.write_bytes(case.encode())

    report = scan([path])
    record = report["files"][0]
    assert record["status"] == "completed", record["errors"]
    detected = case.attack and bool(case.visible)
    assert record["verdict"] == (
        "injection_detected" if detected else "no_injection_detected"
    )
    assert report["exit_code"] == (1 if detected else 0)
    views = {view["name"]: view for view in record["transparency"]["views"]}
    assert [name for name, view in views.items() if view["same_as"] is None] == list(
        case.distinct
    )
    for name, view in views.items():
        if view["same_as"] is None:
            assert view["run_id"]
            assert view["ocr_text_characters"] == (
                len(case.text) if name in case.visible else 0
            )
        expected = SCORE if case.attack and name in case.visible else None
        if expected is not None:
            assert view["score"] == expected, name


def test_opaque_rgba_scans_like_before(tmp_path, visible_text):
    """No transparent pixel: one OCR run, no `transparency` report object."""
    from PIL import Image

    visible_text.text = PAYLOAD
    path = tmp_path / "opaque.png"
    Image.fromarray(opaque_rgba()).save(path)
    report = scan([path])
    record = report["files"][0]
    assert "transparency" not in record
    assert record["verdict"] == "injection_detected"
    runs = list((tmp_path / "cache").rglob("runs/*/input.png"))
    assert len(runs) == 1


def test_failed_view_ocr_makes_the_scan_incomplete(tmp_path, visible_text, monkeypatch):
    from vipi.ocr.session import OcrSession

    case = CASES[0]  # T01: white and black views
    visible_text.text = case.text
    original = OcrSession.extract
    calls = []

    def extract(self, image, on_event=None):
        calls.append(image)
        if len(calls) == 2:
            raise RuntimeError("Fixture OCR failure")
        return original(self, image, on_event)

    monkeypatch.setattr(OcrSession, "extract", extract)
    path = tmp_path / "logo.png"
    path.write_bytes(case.encode())
    report = scan([path])
    record = report["files"][0]
    assert report["exit_code"] == 2
    assert record["status"] == "error"
    assert any("black transparency view" in error for error in record["errors"])
    views = {view["name"]: view for view in record["transparency"]["views"]}
    assert views["black"]["error"] == "Fixture OCR failure"


@pytest.mark.parametrize("detector", ["jev", "openai"])
def test_cloud_image_check_covers_every_distinct_view(
    tmp_path, visible_text, monkeypatch, scanner_runtime, detector
):
    """With no text finding, each distinct view is submitted until one detects."""
    provider, _ = scanner_runtime
    case = CASES[1]  # T02: the text is only in the raw colour channels
    visible_text.text = "Read this label"
    submitted = []

    def check_image(image):
        shown = shows_text(image)
        submitted.append(shown)
        return {"status": "completed", "probability": SCORE if shown else 0.0}

    monkeypatch.setattr(provider, "check_image", check_image, raising=False)
    monkeypatch.setenv("GOOGLE_CLOUD_API_KEY", "fixture-google")
    path = tmp_path / "image.png"
    path.write_bytes(case.encode())

    report = scan([path], ocr_execution_mode="cloud", detector=detector)
    assert report["errors"] == []
    record = report["files"][0]
    assert report["evidence_scope"] == "final_ocr_with_image_check"
    assert record["verdict"] == "injection_detected"
    assert submitted == [False, False, True]
    views = {view["name"]: view for view in record["transparency"]["views"]}
    assert views["rgb"]["image_check"]["verdict"] == "injection_detected"
    assert views["white"]["image_check"]["verdict"] == "no_injection_detected"
