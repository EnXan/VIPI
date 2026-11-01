from research.ocr_eval.experiments.upscale import recognize_upscaled
from PIL import Image
import pytest

from vipi.ocr.recovery.upscale_retry import (
    retained_confident_tokens,
)


def test_upscaled_native_regions_map_back_to_original():
    class Engine:
        def recognize(self, image):
            assert image.size == (200, 100)
            return {
                "text": "word",
                "regions": [
                    {
                        "text": "word",
                        "confidence": 0.99,
                        "polygon": [[20, 20], [80, 20], [80, 40], [20, 40]],
                    }
                ],
            }

    result = recognize_upscaled(Image.new("RGB", (100, 50)), Engine())
    assert result["text"] == "word"
    assert result["step"]["regions"][0]["input_polygon"] == [
        [10, 10],
        [40, 10],
        [40, 20],
        [10, 20],
    ]


def test_guard_detects_lost_confident_words_but_ignores_weak_ocr():
    regions = [
        {"text": "approved", "confidence": 0.99},
        {"text": "noise", "confidence": 0.3},
    ]
    assert retained_confident_tokens(regions, "approval") == ["approved"]
    assert retained_confident_tokens(regions, "approved again") == []


def test_guard_detects_missing_repeated_confident_word():
    regions = [
        {"text": "same", "confidence": 0.99},
        {"text": "same", "confidence": 0.99},
    ]
    assert retained_confident_tokens(regions, "same") == ["same"]


def test_guard_requires_available_confident_evidence():
    with pytest.raises(ValueError, match="No confident OCR tokens"):
        retained_confident_tokens(
            [{"text": "uncertain", "confidence": 0.3}], "uncertain"
        )
