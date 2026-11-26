"""OpenStego evidence through the scanner with inert bytes and fake inference."""

import json
from pathlib import Path
import struct

import numpy as np
from PIL import Image
import pytest

from vipi.openstego import read_openstego
from vipi.scanner import scan

MARKER_TEXT = "VIPI test marker"
RANDOM_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "openstego"
RANDOM_MARKER = "VIPI RandomLSB coverage marker"


def fixture_png(path, data, *, length=None, channel_bits=1, flags=(0, 0)):
    name = b"fixture.txt"
    header = b"OPENSTEGO" + struct.pack(
        "<BIBBBB",
        1,
        len(data) if length is None else length,
        channel_bits,
        len(name),
        *flags,
    )
    samples = np.full(36 * 16 * 3, 128, dtype=np.uint8)
    bits = np.unpackbits(np.frombuffer(header + name + data, dtype=np.uint8))
    samples[: bits.size] |= bits
    Image.fromarray(samples.reshape(16, 36, 3)).save(path)
    return path


def test_openstego_text_is_checked_as_a_separate_reading(tmp_path, scanner_runtime):
    provider, _ = scanner_runtime

    def check(request, image=None):
        provider.calls.append(request)
        return {
            "status": "completed",
            "probability": 0.9 if MARKER_TEXT in json.dumps(request) else 0.0,
        }

    provider.check = check
    payload = "VIPI\u200b test marker".encode()
    path = fixture_png(tmp_path / "image.png", payload)
    report = scan([path])
    record = report["files"][0]
    assert report["exit_code"] == 1
    assert record["verdict"] == "injection_detected"
    assert record["openstego"] == {
        "status": "text",
        "stored_bytes": len(payload),
        "characters": len(payload.decode()),
        "invisible_characters": 1,
        "scores": {"ocr": 0.0, "openstego": 0.9},
    }
    assert len(provider.calls) == 2
    (reading,) = read_openstego(path.read_bytes())
    assert reading.text == payload.decode()
    assert reading.detector_text == MARKER_TEXT


@pytest.mark.parametrize(
    "data,header,status,exit_code",
    [
        (b"\xff\x00", {}, "binary", 0),
        (b"fixture", {"flags": (1, 0)}, "compressed", 2),
        (b"fixture", {"flags": (1, 1)}, "encrypted", 2),
        (b"fixture", {"length": 2**32 - 1}, "malformed", 2),
        (b"fixture", {"channel_bits": 2}, "unsupported", 2),
    ],
)
def test_openstego_data_statuses(
    tmp_path, scanner_runtime, data, header, status, exit_code
):
    provider, _ = scanner_runtime
    provider.score = 0.0
    path = fixture_png(tmp_path / "image.png", data, **header)
    report = scan([path])
    record = report["files"][0]
    assert report["exit_code"] == exit_code
    assert record["verdict"] == (None if exit_code else "no_injection_detected")
    assert record["openstego"]["status"] == status
    assert len(provider.calls) == 1


def test_ordinary_png_does_not_add_a_reading(tmp_path, scanner_runtime):
    provider, _ = scanner_runtime
    provider.score = 0.0
    path = tmp_path / "image.png"
    Image.new("RGB", (36, 16), "white").save(path)
    report = scan([path])
    assert "openstego" not in report["files"][0]
    assert report["exit_code"] == 0
    assert len(provider.calls) == 1


def test_upstream_random_lsb_plaintext_is_checked(scanner_runtime):
    provider, _ = scanner_runtime

    def check(request, image=None):
        provider.calls.append(request)
        return {
            "status": "completed",
            "probability": 0.9 if RANDOM_MARKER in json.dumps(request) else 0.0,
        }

    provider.check = check
    # OpenStego 0.8.6 used two bits for the data and one for the header.
    path = RANDOM_FIXTURES / "random-lsb-two-bit.png"
    (reading,) = read_openstego(path.read_bytes())
    assert reading.text == f"{RANDOM_MARKER}\n" + "Harmless fixture text.\n" * 45
    report = scan([path])
    assert report["exit_code"] == 1
    record = report["files"][0]
    assert "openstego" not in record
    random_lsb = record["openstego_random_lsb"]
    assert random_lsb["status"] == "text"
    assert random_lsb["scores"] == {"ocr": 0, "openstego_random_lsb": 0.9}


def test_upstream_random_lsb_default_compression_is_reported(scanner_runtime):
    provider, _ = scanner_runtime
    provider.score = 0.0
    report = scan([RANDOM_FIXTURES / "random-lsb-compressed.png"])
    assert report["exit_code"] == 2
    record = report["files"][0]
    assert record["openstego_random_lsb"]["status"] == "compressed"
    assert record["verdict"] is None
    assert len(provider.calls) == 1
