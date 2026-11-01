from PIL import Image
import pytest

from research.ocr_eval.evaluation.missing_text import (
    find_uncovered,
    recognize_uncovered,
)


def region(text, x, confidence=0.99, line="1"):
    return {
        "text": text,
        "confidence": confidence,
        "line_id": line,
        "input_polygon": [[x, 0], [x + 20, 0], [x + 20, 10], [x, 10]],
    }


def test_detects_new_location_and_groups_words_by_candidate_line():
    old = [region("existing", 0)]
    new = [region("existing", 0), region("hidden", 40), region("words", 65)]
    result = find_uncovered(old, new)
    assert len(result) == 1
    assert result[0]["text"] == "hidden words"
    assert result[0]["box"] == [40, 0, 85, 10]


def test_excludes_low_confidence():
    assert find_uncovered([], [region("weak", 0, confidence=0.4)]) == []


def test_rereads_each_line_with_two_independent_transforms_and_maps_coordinates():
    class Engine:
        def recognize(self, image):
            return {
                "text": "hidden",
                "regions": [
                    {
                        "text": "hidden",
                        "polygon": [[20, 20], [40, 20], [40, 40], [20, 40]],
                    }
                ],
            }

    image = Image.new("RGB", (100, 100), "white")
    values = recognize_uncovered(image, [{"box": [20, 20, 40, 30]}], Engine())
    assert [x["source"] for x in values] == ["upscale-2x", "green-minus-red-2x"]
    assert values[0]["regions"][0]["input_polygon"][0] == [20, 20]


def test_missing_geometry_is_unavailable_rather_than_a_clear_signal():
    with pytest.raises(ValueError, match="Incumbent OCR region geometry unavailable"):
        find_uncovered([{"text": "old"}], [region("new", 0)])
    with pytest.raises(ValueError, match="Candidate OCR region geometry unavailable"):
        find_uncovered([region("old", 0)], [{"text": "new"}])
    with pytest.raises(ValueError, match="Candidate OCR region geometry unavailable"):
        find_uncovered([region("old", 0)], [region("new", 0), {"text": "missing"}])
