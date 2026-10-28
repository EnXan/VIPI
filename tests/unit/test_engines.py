import io
import subprocess
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image

from vipi.ocr.engines import MistralEngine, RapidEngine, TesseractEngine


def test_tesseract_preserves_quotes_low_scores_and_lines(tmp_path, monkeypatch):
    monkeypatch.setattr("vipi.ocr.engines.validate_model", lambda *args, **kwargs: None)
    data = (
        "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
        '5\t1\t1\t1\t1\t1\t10\t10\t20\t10\t0\t"hello\n'
        '5\t1\t1\t1\t1\t2\t40\t10\t20\t10\t20\tworld"\n'
        "5\t1\t1\t1\t2\t1\t10\t30\t20\t10\t90\tsecond\n"
    ).encode()

    def run(command, **kwargs):
        assert "tessedit_create_tsv=1" in command
        assert kwargs["input"].startswith(b"\x89PNG")
        assert kwargs["env"]["OMP_THREAD_LIMIT"] == "2"
        return subprocess.CompletedProcess(command, 0, data, b"")

    monkeypatch.setattr("vipi.ocr.engines.subprocess.run", run)
    output = TesseractEngine(tmp_path, threads=2).recognize(Image.new("RGB", (100, 50)))
    assert output["text"] == '"hello world"\nsecond'
    assert len(output["regions"]) == 3
    assert output["regions"][0]["confidence"] == 0
    assert output["regions"][0]["polygon"][2] == [30, 20]


def test_native_failure_is_an_error_even_without_stderr(tmp_path, monkeypatch):
    monkeypatch.setattr("vipi.ocr.engines.validate_model", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "vipi.ocr.engines.subprocess.run",
        lambda command, **kwargs: subprocess.CompletedProcess(command, -6, b"", b""),
    )
    with pytest.raises(RuntimeError, match="code -6"):
        TesseractEngine(tmp_path).recognize(Image.new("RGB", (1, 1)))


def test_partial_word_boxes_do_not_drop_recognized_line_text():
    box = [[0, 0], [90, 0], [90, 20], [0, 20]]

    class OCR:
        text_det = SimpleNamespace(
            preprocess_op=SimpleNamespace(
                mean=np.array([0.5] * 3), std=np.array([0.5] * 3)
            )
        )

        def __call__(self, image):
            return SimpleNamespace(
                txts=("keep all text",),
                boxes=[box],
                scores=(0.1,),
                word_results=((("keep", 0.1, box),),),
            )

    engine = RapidEngine.__new__(RapidEngine)
    engine.ocr = OCR()
    engine.recognizer_shapes = []
    result = engine.recognize(Image.new("RGB", (100, 30)))
    assert result["regions"][0]["text"] == "keep all text"
    assert result["regions"][0]["level"] == "line"


def test_mistral_request_and_result_use_image_coordinates(monkeypatch):
    import base64
    import json

    import vipi.ocr.engines as engines

    monkeypatch.setattr(engines, "api_key", lambda name: "test-key")

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return json.dumps(
                {
                    "model": "mistral-ocr-4-1",
                    "pages": [
                        {
                            "dimensions": {"width": 40, "height": 20},
                            "blocks": [
                                {
                                    "type": "text",
                                    "content": "sample text",
                                    "top_left_x": 2,
                                    "top_left_y": 3,
                                    "bottom_right_x": 30,
                                    "bottom_right_y": 12,
                                    "confidence_scores": {
                                        "average_content_confidence_score": 0.9
                                    },
                                }
                            ],
                        }
                    ],
                    "usage_info": {"pages_processed": 1},
                }
            ).encode()

    def urlopen(request, timeout):
        assert request.full_url == "https://api.mistral.ai/v1/ocr"
        assert request.get_header("Authorization") == "Bearer test-key"
        assert timeout == 120
        payload = json.loads(request.data)
        assert payload["model"] == "mistral-ocr-4-1"
        assert payload["include_blocks"] is True
        assert payload["confidence_scores_granularity"] == "block"
        image_data = payload["document"]["image_url"].split(",", 1)[1]
        assert base64.b64decode(image_data).startswith(b"\x89PNG")
        return Response()

    monkeypatch.setattr(engines.urllib.request, "urlopen", urlopen)
    result = MistralEngine().recognize(Image.new("RGB", (20, 10)))
    assert result["text"] == "sample text"
    assert result["regions"][0]["polygon"] == [
        [1.0, 1.5], [15.0, 1.5], [15.0, 6.0], [1.0, 6.0]
    ]
    assert result["regions"][0]["confidence"] == 0.9
    assert result["preprocessing"]["usage_info"] == {"pages_processed": 1}
    assert "test-key" not in json.dumps(result)


def test_mistral_requires_api_key(monkeypatch):
    import vipi.ocr.engines as engines

    monkeypatch.setattr(engines, "api_key", lambda name: None)
    with pytest.raises(ValueError, match="MISTRAL_API_KEY"):
        MistralEngine()


def test_mistral_http_errors_redact_api_key(monkeypatch):
    import json
    import urllib.error

    import vipi.ocr.engines as engines

    monkeypatch.setattr(engines, "api_key", lambda name: "hidden-key")
    monkeypatch.setattr(
        engines.urllib.request,
        "urlopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            urllib.error.HTTPError(
                "https://api.mistral.ai/v1/ocr",
                401,
                "unauthorized",
                {},
                io.BytesIO(json.dumps({"message": "bad key hidden-key"}).encode()),
            )
        ),
    )
    with pytest.raises(RuntimeError, match="bad key") as error:
        MistralEngine().recognize(Image.new("RGB", (2, 2)))
    assert "hidden-key" not in str(error.value)
