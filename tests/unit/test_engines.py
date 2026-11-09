import io
import subprocess
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image

from vipi.ocr.engines import RapidEngine, TesseractEngine, load_rapid_models
from vipi.ocr.cloud import MistralEngine


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


def test_rapid_models_are_loaded_before_provider_check():
    def component(providers):
        session = SimpleNamespace(get_providers=lambda: providers)
        return SimpleNamespace(session=SimpleNamespace(session=session))

    class LazyOCR:
        # RapidOCR 3.10 leaves both models unset until first use.
        text_det = text_rec = None

        def _load_det_model(self):
            self.text_det = component(["CPUExecutionProvider"])
            return self.text_det

        def _load_rec_model(self):
            self.text_rec = component(["CoreMLExecutionProvider"])
            return self.text_rec

    ocr = LazyOCR()
    assert load_rapid_models(ocr) == {
        "detector": ["CPUExecutionProvider"],
        "recognizer": ["CoreMLExecutionProvider"],
    }
    assert ocr.text_det is not None and ocr.text_rec is not None


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


def test_google_vision_resizes_only_when_request_exceeds_provider_limit(monkeypatch):
    import base64
    import json

    import vipi.ocr.cloud as cloud

    monkeypatch.setattr(cloud, "api_key", lambda name, *args: "fixture-key")
    monkeypatch.setattr(cloud, "GOOGLE_REQUEST_MAX_BYTES", 5_000)
    image_array = np.random.default_rng(4).integers(
        0, 256, (128, 128, 3), dtype=np.uint8
    )
    image = Image.fromarray(image_array)
    submitted_size = None
    request_bytes = None

    def request_json(url, payload, key, *, bearer=True):
        nonlocal submitted_size, request_bytes
        assert url == "https://vision.googleapis.com/v1/images:annotate"
        assert key == "fixture-key" and bearer is False
        request_bytes = len(json.dumps(payload).encode("utf-8"))
        encoded = payload["requests"][0]["image"]["content"]
        with Image.open(io.BytesIO(base64.b64decode(encoded))) as submitted:
            submitted_size = submitted.size
        width, height = submitted_size
        return {
            "responses": [
                {
                    "fullTextAnnotation": {
                        "text": "word",
                        "pages": [
                            {
                                "blocks": [
                                    {
                                        "paragraphs": [
                                            {
                                                "words": [
                                                    {
                                                        "symbols": [{"text": "word"}],
                                                        "boundingBox": {
                                                            "vertices": [
                                                                {"x": 0, "y": 0},
                                                                {"x": width, "y": 0},
                                                                {
                                                                    "x": width,
                                                                    "y": height,
                                                                },
                                                                {"x": 0, "y": height},
                                                            ]
                                                        },
                                                    }
                                                ]
                                            }
                                        ]
                                    }
                                ]
                            }
                        ],
                    }
                }
            ]
        }

    monkeypatch.setattr(cloud, "request_json", request_json)
    result = cloud.GoogleVisionEngine().recognize(image)

    assert submitted_size is not None and max(submitted_size) < 128
    assert request_bytes is not None and request_bytes <= 5_000
    assert result["regions"][0]["polygon"] == [
        [0, 0],
        [128.0, 0],
        [128.0, 128.0],
        [0, 128.0],
    ]
    assert result["preprocessing"]["input_size"] == [128, 128]
    assert result["preprocessing"]["submitted_size"] == list(submitted_size)
    assert result["preprocessing"]["resize"] == "google-json-request-limit"


def test_mistral_request_and_result_use_image_coordinates(monkeypatch):
    import base64
    import json

    import vipi.ocr.cloud as engines

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
        [1.0, 1.5],
        [15.0, 1.5],
        [15.0, 6.0],
        [1.0, 6.0],
    ]
    assert result["regions"][0]["confidence"] == 0.9
    assert result["preprocessing"]["usage_info"] == {"pages_processed": 1}
    assert "test-key" not in json.dumps(result)


def test_mistral_requires_api_key(monkeypatch):
    import vipi.ocr.cloud as engines

    monkeypatch.setattr(engines, "api_key", lambda name: None)
    with pytest.raises(ValueError, match="MISTRAL_API_KEY"):
        MistralEngine()


def test_mistral_http_errors_redact_api_key(monkeypatch):
    import json
    import urllib.error

    import vipi.ocr.cloud as engines

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
