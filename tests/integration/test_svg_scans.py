"""L2: every SVG technique through a full scan with fake OCR and detector.

The fake OCR never reads the payload, so a case is detected only through the
SVG source reading. Cases whose payload only the render shows (outcome `ocr`)
need real OCR (L3) and end without a detection here.
"""

import json

import pytest

from tests.svg_cases import CASES, ERROR, PAYLOAD, Assets, expected_verdict
from vipi.scanner import scan

SCORE = 0.9


@pytest.fixture
def payload_detector(scanner_runtime):
    provider, _ = scanner_runtime

    def check(payload, image=None):
        provider.calls.append(payload)
        found = PAYLOAD in json.dumps(payload, ensure_ascii=False)
        return {"status": "completed", "probability": SCORE if found else 0.0}

    provider.check = check
    return provider


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.id)
def test_scan(case, tmp_path, payload_detector):
    assets = Assets.create(tmp_path / "assets")
    path = tmp_path / f"{case.id}.svg"
    path.write_bytes(case.svg(PAYLOAD, assets))

    report = scan([path])
    record = report["files"][0]
    verdict = expected_verdict(case)

    # An embedded font leaves the scan incomplete even when a reading is
    # detected: errors take precedence over detections (docs/cli.md).
    incomplete = case.outcome == ERROR or "embedded_font" in case.features
    assert record.get("verdict") == verdict
    detected = verdict == "injection_detected"
    assert report["exit_code"] == (2 if incomplete else 1 if detected else 0)
    assert (record["status"] == "error") == incomplete
    if case.outcome == ERROR:
        assert record["errors"][0].startswith(case.error)
        assert "svg" not in record
        return
    svg = record["svg"]
    assert svg["features"] == sorted(case.features)
    assert svg["removed_references"] == [assets.format(item) for item in case.removed]
    assert (svg["scores"].get("svg_source") == SCORE) == (
        case.in_source or case.decoded
    )
    assert any("embeds a font" in error for error in record["errors"]) == incomplete


def test_binary_base64_in_svg_metadata_adds_no_decoded_check(tmp_path, payload_detector):
    """A C2PA manifest is binary: ADR 0079 decoding checks only text plaintext."""
    from tests.svg_cases import BENIGN, benign_svg
    from vipi.scanner import scan_image

    case = next(case for case in BENIGN if case.id == "B02-c2pa")
    path = tmp_path / "logo.svg"
    path.write_bytes(benign_svg(case))
    result = scan_image(path, provider=payload_detector)
    kinds = [answer["kind"] for answer in result.detection.answers]
    assert "decoded" not in kinds
    assert result.detection.verdict == "no_injection_detected"
