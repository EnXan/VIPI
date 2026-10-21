import pytest

from vipi.config import OCR_MODEL_IDS
from vipi.ocr.models import FILES, PUBLIC_MODEL_NAMES, REQUIRED


@pytest.mark.parametrize(
    ("model", "size"),
    [
        ("ppocr-v6-tiny", "tiny"),
        ("ppocr-v6-small", "small"),
        ("ppocr-v6", "medium"),
        ("ppocr-v6-medium", "medium"),
    ],
)
def test_ppocrv6_model_ids_have_pinned_detection_and_recognition_files(model, size):
    detector, recognizer, classifier = REQUIRED[model]

    assert FILES[detector]["file"] == f"PP-OCRv6_det_{size}.onnx"
    assert FILES[recognizer]["file"] == f"PP-OCRv6_rec_{size}.onnx"
    assert classifier == "ch_PP-LCNet_x0_25_textline_ori_cls_mobile"
    assert FILES[detector]["sha256"]
    assert FILES[recognizer]["sha256"]


def test_mode_models_are_exposed_and_tesseract_is_not_a_cli_choice():
    assert set(PUBLIC_MODEL_NAMES) >= {
        "ppocr-v6-tiny",
        "ppocr-v6-small",
        "ppocr-v6",
    }
    assert "tesseract" not in OCR_MODEL_IDS
