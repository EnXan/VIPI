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
def test_cloud_scan_submits_the_whole_image_after_no_text_finding(
    monkeypatch, scanner_runtime, name, size
):
    monkeypatch.setenv("TYPESAFE_API_KEY", "fixture-jev")
    monkeypatch.setenv("OPENAI_API_KEY", "fixture-openai")
    monkeypatch.setenv("GOOGLE_CLOUD_API_KEY", "fixture-google")
    images = []

    def transport(url, key, body, **kwargs):
        if name == "jev":
            image = "<image>" in body.get("assets", {})
            if image:
                assert kwargs["headers"] == {"TypeSafe-Danger-Zone-Images": "true"}
                assert body["state"]["untrusted_evidence"] == {"image": "<image>"}
                encoded = body["assets"]["<image>"]["data_base64"]
            assert body["questions"][QUESTION_ID]["instructions"] == INSTRUCTIONS
            score = 0.8 if image else 0.1
            answers = {QUESTION_ID: {"type": "noul", "noul": score}}
        else:
            content = body["input"][0]["content"]
            image = len(content) == 2
            if image:
                text, supplied = content
                evidence = json.loads(text["text"])["untrusted_evidence"]
                assert evidence.keys() == {"image"}
                assert supplied["detail"] == "original"
                _, encoded = supplied["image_url"].split(",", 1)
            assert body["questions"][0]["instructions"] == INSTRUCTIONS
            score = 0.8 if image else 0.1
            answers = [{"name": QUESTION_ID, "type": "predicate", "probability": score}]
        if image:
            images.append(encoded)
        return {"answers": answers, "usage": {"input_tokens": 1000}}, {"attempts": 1}

    model = Jev if name == "jev" else Decisions
    monkeypatch.setattr(
        "vipi.detection.providers.create_provider",
        lambda selected, model_dir: model(transport=transport),
    )
    Image.new("RGB", (32, 24), "red").save("image.png")
    detector = ["--detector", "jev"] if name == "jev" else []
    assert (
        main(
            [
                "scan",
                "image.png",
                "--modus",
                "cloud",
                *detector,
                "--output",
                "report.json",
            ]
        )
        == 1
    )
    report = json.loads(Path("report.json").read_text())
    record = report["files"][0]
    assert report["evidence_scope"] == "final_ocr_with_image_check"
    assert report["detector"] == name
    assert record["image_check"]["submitted_image_size"] == list(size)
    assert record["image_check"]["verdict"] == "injection_detected"
    assert len(images) == 1
    with Image.open(BytesIO(base64.b64decode(images[0]))) as submitted:
        assert submitted.size == size
        assert submitted.getpixel((0, 0)) == (255, 0, 0)
        assert submitted.getpixel((31, 23)) == (255, 0, 0)


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
