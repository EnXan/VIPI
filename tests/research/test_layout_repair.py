import json

from PIL import Image

from research.ocr_eval.experiments.layout_repair import native_line_layout
from research.ocr_eval.experiments.decisions import ResearchDecider


def word(text, line_id, x, y):
    polygon = [[x, y], [x + 20, y], [x + 20, y + 10], [x, y + 10]]
    return {
        "text": text,
        "line_id": line_id,
        "polygon": polygon,
        "input_polygon": polygon,
        "confidence": 0.9,
        "level": "word",
    }


def test_alternative_keeps_words_in_their_native_lines():
    step = {
        "id": "0001",
        "text": "first line\nsecond line",
        "regions": [
            word("first", "a", 0, 0),
            word("line", "a", 25, 0),
            word("second", "b", 0, 20),
            word("line", "b", 25, 20),
        ],
    }
    result = native_line_layout(step, "second line\nfirst line")
    assert result["text"] == "first line\nsecond line"
    assert [group["text"] for group in result["groups"]] == [
        "first line",
        "second line",
    ]


def test_no_candidate_when_words_cannot_be_preserved():
    step = {"id": "0001", "text": "first", "regions": [word("first", "a", 0, 0)]}
    assert native_line_layout(step, "different") is None
    step["regions"][0].pop("line_id")
    assert native_line_layout(step, "first") is None


def test_layout_review_sends_actual_groups_and_image(tmp_path, monkeypatch):
    def transport(url, key, payload, **options):
        return {
            "answers": [
                {
                    "name": "layout",
                    "type": "choice",
                    "choice": "incumbent",
                    "confidence": 0.9,
                }
            ],
            "usage": {},
        }, {}

    monkeypatch.setenv("OPENAI_API_KEY", "fixture-key")
    old = {"text": "old", "groups": [{"text": "old", "box": [0, 0, 20, 10]}]}
    new = {"text": "new", "groups": [{"text": "new", "box": [0, 0, 20, 10]}]}
    ResearchDecider(transport=transport).compare_layout(
        Image.new("RGB", (100, 100)), old, new, tmp_path
    )
    saved = json.loads((tmp_path / "request.json").read_text())
    assert saved["state"]["incumbent"] == old
    assert saved["state"]["candidate"] == new
    assert saved["images"][0]["reference"] == "<original-image>"
    assert "reference" not in saved["state"]
