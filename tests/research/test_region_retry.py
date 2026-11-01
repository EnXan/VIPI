import json

from PIL import Image

from research.ocr_eval.experiments.region_retry import apply_approved, retry_regions
from research.ocr_eval.experiments.decisions import ResearchDecider


class Engine:
    def __init__(self, text="correct", confidence=0.99):
        self.text = text
        self.confidence = confidence
        self.calls = 0

    def recognize(self, image):
        self.calls += 1
        return {
            "regions": [
                {
                    "text": self.text,
                    "confidence": self.confidence,
                    "polygon": [[20, 20], [60, 20], [60, 40], [20, 40]],
                }
            ]
        }


def test_retries_a_uniquely_mapped_weak_region():
    image = Image.new("RGB", (100, 100))
    step = {
        "regions": [
            {
                "text": "wrong",
                "confidence": 0.3,
                "input_polygon": [[20, 20], [40, 20], [40, 30], [20, 30]],
            }
        ]
    }
    groups = [{"text": "a wrong word", "box": [10, 15, 80, 35]}]
    engine = Engine()
    result = retry_regions(image, step, groups, engine)
    assert result["text"] == "a correct word"
    assert groups[0]["text"] == "a wrong word"
    assert len(result["changes"]) == engine.calls == 1


def test_uncertain_candidate_keeps_original():
    image = Image.new("RGB", (100, 100))
    step = {
        "regions": [
            {
                "text": "wrong",
                "confidence": 0.3,
                "input_polygon": [[20, 20], [40, 20], [40, 30], [20, 30]],
            }
        ]
    }
    groups = [{"text": "a wrong word", "box": [10, 15, 80, 35]}]
    result = retry_regions(image, step, groups, Engine(confidence=0.8))
    assert result["text"] == "a wrong word"
    assert not result["changes"]


def test_visual_comparison_receives_actual_independent_readings(tmp_path, monkeypatch):
    def transport(url, key, payload, **options):
        return {
            "answers": [
                {
                    "name": "reading_0",
                    "type": "choice",
                    "choice": "original",
                    "confidence": 0.9,
                }
            ],
            "usage": {},
        }, {}

    monkeypatch.setenv("OPENAI_API_KEY", "fixture-key")
    changes = [{"old": "Orders", "new": "Ordt", "box": [20, 20, 40, 30]}]
    ResearchDecider(transport=transport).compare_region_readings(
        Image.new("RGB", (100, 100)), changes, tmp_path
    )
    request = json.loads((tmp_path / "request.json").read_text())
    assert request["state"]["regions"][0]["original_reading"] == "Orders"
    assert request["state"]["regions"][0]["new_reading"] == "Ordt"
    assert len(request["questions"]) == 1


def test_apply_only_approved_readings():
    groups = [{"text": "Orders and wrong", "box": [0, 0, 100, 20]}]
    changes = [
        {"old": "Orders", "new": "Ordt", "box": [1, 1, 20, 10]},
        {"old": "wrong", "new": "correct", "box": [60, 1, 80, 10]},
    ]
    result = apply_approved(groups, changes, [False, True])
    assert result["text"] == "Orders and correct"
    assert len(result["changes"]) == 1


def test_replacement_audit_sends_missing_ocr_tokens_and_location(tmp_path, monkeypatch):
    def transport(url, key, payload, **options):
        return {
            "answers": [
                {
                    "name": "replacement",
                    "type": "choice",
                    "choice": "incumbent",
                    "confidence": 0.9,
                }
            ],
            "usage": {},
        }, {}

    monkeypatch.setenv("OPENAI_API_KEY", "fixture-key")
    old = {
        "text": "I will help",
        "groups": [
            {
                "text": "I will help",
                "input_polygon": [[10, 10], [80, 10], [80, 30], [10, 30]],
            }
        ],
    }
    new = {"text": "I help", "groups": []}
    ResearchDecider(transport=transport).verify_replacement(
        Image.new("RGB", (100, 100)), old, new, tmp_path
    )
    request = json.loads((tmp_path / "request.json").read_text())
    assert request["state"]["incumbent_tokens_missing_in_candidate"] == ["will"]
    assert request["state"]["potential_loss_image"] == "<potential-loss-region>"
