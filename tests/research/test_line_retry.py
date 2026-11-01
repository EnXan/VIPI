from PIL import Image

from research.ocr_eval.experiments.line_retry import (
    apply_line_choices,
    retry_ambiguous_lines,
)


def word(text, box):
    x, y, r, b = box
    polygon = [[x, y], [r, y], [r, b], [x, b]]
    return {
        "text": text,
        "line_id": "line",
        "polygon": polygon,
        "input_polygon": polygon,
        "confidence": 0.99,
        "level": "word",
    }


def test_retries_one_whole_line_and_changes_only_the_ambiguous_glyph():
    class Engine:
        def __init__(self):
            self.calls = 0

        def recognize(self, image):
            self.calls += 1
            return {
                "text": "Type II current",
                "regions": [
                    {"text": "II", "polygon": [[60, 20], [68, 20], [68, 40], [60, 40]]}
                ],
            }

    engine = Engine()
    step = {
        "id": "0001",
        "text": "Type l current",
        "regions": [
            word("Type", (0, 10, 25, 20)),
            word("l", (30, 10, 34, 20)),
            word("current", (40, 10, 80, 20)),
        ],
    }
    groups = [
        {
            "text": "Header | Type l current",
            "input_polygon": [[0, 10], [80, 10], [80, 20], [0, 20]],
        }
    ]
    result = retry_ambiguous_lines(Image.new("RGB", (100, 50)), step, groups, engine)
    assert engine.calls == 1
    assert result["proposals"][0]["new"] == "Type II current"
    accepted = apply_line_choices(groups, result["proposals"], [True])
    assert accepted["text"] == "Header | Type II current"
    assert groups[0]["text"] == "Header | Type l current"
    assert (
        apply_line_choices(groups, result["proposals"], [False])["text"]
        == groups[0]["text"]
    )


def test_no_extra_ocr_for_line_without_an_ambiguous_glyph():
    class Engine:
        def recognize(self, image):
            raise AssertionError("unexpected OCR")

    step = {
        "id": "0001",
        "text": "ordinary line",
        "regions": [word("ordinary", (0, 0, 30, 10)), word("line", (40, 0, 70, 10))],
    }
    assert (
        retry_ambiguous_lines(Image.new("RGB", (100, 50)), step, [], Engine())[
            "attempts"
        ]
        == []
    )
