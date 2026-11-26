"""Declared, headerless PNG layouts through the existing scan entry point."""

import json

import numpy as np
from PIL import Image
import pytest

from vipi.cli import main
from vipi.scanner import scan

MARKER = "VIPI LSB test marker"
LAYOUT = "b1,rgb,lsb,xy"


def marker_png(path):
    samples = np.full(36 * 16 * 3, 128, dtype=np.uint8)
    bits = np.unpackbits(np.frombuffer(MARKER.encode("ascii"), dtype=np.uint8))
    samples[: bits.size] |= bits
    Image.fromarray(samples.reshape(16, 36, 3)).save(path)
    return path


def test_declared_layout_adds_a_text_reading(tmp_path, scanner_runtime, capsys):
    provider, _ = scanner_runtime

    def check(request, image=None):
        provider.calls.append(request)
        return {
            "status": "completed",
            "probability": 0.9 if MARKER in json.dumps(request) else 0,
        }

    provider.check = check
    image = marker_png(tmp_path / "original.png")
    default = scan([image])
    assert default["exit_code"] == 0
    assert "png_lsb" not in default["files"][0]

    output = tmp_path / "report.json"
    assert (
        main(
            [
                "scan",
                str(image),
                "--lsb-layout",
                LAYOUT,
                "--lsb-layout",
                LAYOUT,
                "--verbose",
                "--output",
                str(output),
            ]
        )
        == 1
    )
    record = json.loads(output.read_text())["files"][0]
    assert record["verdict"] == "injection_detected"
    assert record["png_lsb"]["layouts"] == [LAYOUT]
    assert record["png_lsb"]["scores"] == {"ocr": 0, "png_lsb": 0.9}
    assert len(provider.calls) == 3
    assert MARKER in capsys.readouterr().out


@pytest.mark.parametrize("layout", ["b1,rgb,lsb,yx", "b2,rgb,lsb,xy"])
def test_layout_is_actually_applied(tmp_path, scanner_runtime, layout):
    provider, _ = scanner_runtime
    provider.score = 0
    image = marker_png(tmp_path / "original.png")
    # A different layout may surface noise, but never this expected marker.
    scan([image], lsb_layouts=(layout,))
    assert all(MARKER not in json.dumps(request) for request in provider.calls)


def test_invalid_layout_fails_before_scanning(tmp_path, scanner_runtime):
    provider, _ = scanner_runtime
    image = marker_png(tmp_path / "original.png")
    report = scan([image], lsb_layouts=("b9,rgb,lsb,xy",))
    assert report["exit_code"] == 2
    assert "Use an LSB layout" in report["errors"][0]["error"]
    assert not provider.calls
