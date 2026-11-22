import base64
from io import BytesIO
import json
from pathlib import Path

from PIL import Image
import pytest

from vipi.cli import main
from vipi.detection.policy import INSTRUCTIONS, QUESTION_ID
from vipi.detection.providers.jev import Jev
from vipi.detection.providers.openai import Decisions
from vipi.scanner import scan


@pytest.mark.parametrize("name,size", [("jev", (280, 280)), ("openai", (32, 24))])
def test_image_only_cli_submits_pixels_and_skips_ocr(tmp_path, monkeypatch, name, size):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("TYPESAFE_API_KEY", "fixture-jev")
    monkeypatch.setenv("OPENAI_API_KEY", "fixture-openai")
    monkeypatch.setenv("GOOGLE_CLOUD_API_KEY", "")
    monkeypatch.setenv("GOOGLE_API_KEY", "")
    calls = []

    def unexpected(*args, **kwargs):
        pytest.fail("--image-only must skip the OCR session")

    def transport(url, key, body, **kwargs):
        calls.append((url, key))
        if name == "jev":
            assert kwargs["headers"] == {"TypeSafe-Danger-Zone-Images": "true"}
            assert body["state"]["untrusted_evidence"] == {"image": "<image>"}
            assert body["questions"][QUESTION_ID]["instructions"] == INSTRUCTIONS
            encoded = body["assets"]["<image>"]["data_base64"]
            answers = {QUESTION_ID: {"type": "noul", "noul": 0.8}}
        else:
            text, supplied = body["input"][0]["content"]
            assert json.loads(text["text"])["untrusted_evidence"].keys() == {"image"}
            assert supplied["detail"] == "original"
            assert body["questions"][0]["instructions"] == INSTRUCTIONS
            _, encoded = supplied["image_url"].split(",", 1)
            answers = [{"name": QUESTION_ID, "type": "predicate", "probability": 0.8}]
        with Image.open(BytesIO(base64.b64decode(encoded))) as submitted:
            assert submitted.size == size
            assert submitted.getpixel((0, 0)) == (255, 0, 0)
            assert submitted.getpixel((31, 23)) == (255, 0, 0)
        return {"answers": answers, "usage": {"input_tokens": 1000}}, {"attempts": 1}

    model = Jev if name == "jev" else Decisions
    monkeypatch.setattr("vipi.ocr.session.OcrSession", unexpected)
    monkeypatch.setattr(
        "vipi.detection.providers.create_provider",
        lambda selected, model_dir: model(transport=transport),
    )
    Image.new("RGB", (32, 24), "red").save("image.png")
    detector = ["--detector", "jev"] if name == "jev" else []
    assert (
        main(
            ["scan", "image.png", "--image-only", *detector, "--output", "report.json"]
        )
        == 1
    )
    report = json.loads(Path("report.json").read_text())
    record = report["files"][0]
    assert report["evidence_scope"] == "image_only"
    assert report["detector"] == name
    assert report["ocr"] is report["ocr_model"] is None
    assert record["ocr_passes"] == 0
    assert record["image_check"]["submitted_image_size"] == list(size)
    assert record["image_check"]["verdict"] == "injection_detected"
    assert record["detection_cost"]["api_calls"] == len(calls) == 1
    assert (
        record["estimated_total_api_cost_usd"]
        == record["detection_cost"]["estimated_usd"]
    )
    assert (Path(record["artifacts"]) / "input.png").is_file()


@pytest.mark.parametrize(
    "text_score,image_score,code,verdict,calls",
    [
        (0.8, 0.99, 1, "injection_detected", 0),
        (0.1, 0.9, 1, "injection_detected", 1),
        (0.1, 0.2, 0, "no_injection_detected", 1),
        (0.1, None, 2, None, 1),
    ],
)
@pytest.mark.parametrize("detector", ["jev", "openai"])
def test_cloud_scan_checks_the_image_only_after_no_text_finding(
    tmp_path,
    monkeypatch,
    scanner_runtime,
    text_score,
    image_score,
    code,
    verdict,
    calls,
    detector,
):
    provider, _ = scanner_runtime
    provider.score = text_score
    images = []

    def check_image(image):
        images.append(image.size)
        assert len(provider.calls) == 1
        if image_score is None:
            return {"status": "refused", "error": "Fixture refused the image."}
        return {"status": "completed", "probability": image_score}

    monkeypatch.setattr(provider, "check_image", check_image, raising=False)
    monkeypatch.setenv("GOOGLE_CLOUD_API_KEY", "fixture-google")
    path = tmp_path / "image.png"
    Image.new("RGB", (32, 24), "red").save(path)

    report = scan([path], ocr_execution_mode="cloud", detector=detector)
    assert report["evidence_scope"] == "final_ocr_with_image_check"
    assert report["exit_code"] == code
    record = report["files"][0]
    assert record["verdict"] == verdict
    assert images == [(32, 24)] * calls
    assert ("image_check" in record) == bool(calls)
    if image_score is None:
        assert record["errors"] == ["Fixture refused the image."]
