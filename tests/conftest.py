import json

import pytest
from PIL import Image


@pytest.fixture
def scanner_decisions(monkeypatch):
    class Decider:
        model = "fixture-decision"
        provider = "fixture"

        @staticmethod
        def record(name, choice):
            return {
                "response": {
                    "answers": {
                        name: {"type": "choice", "choice": choice, "confidence": 1.0}
                    }
                },
                "estimated_usd": 0.0,
                "attempts": 1,
            }

        def assess(self, *args):
            return {
                "response": {
                    "answers": {
                        "completeness": {
                            "type": "choice",
                            "choice": "complete",
                            "confidence": 1.0,
                        },
                        "reviewability": {
                            "type": "choice",
                            "choice": "sufficient",
                            "confidence": 1.0,
                        },
                        "repair": {
                            "type": "choice",
                            "choice": "none",
                            "confidence": 1.0,
                        },
                    }
                },
                "estimated_usd": 0.0,
                "attempts": 1,
            }

        def compare(self, *args):
            return self.record("comparison", "equivalent")

    for name in ("LocalDecider", "DecisionsDecider", "JevDecider"):
        monkeypatch.setattr(
            "vipi.ocr.session." + name, lambda *args, **kwargs: Decider()
        )
    return Decider


@pytest.fixture
def evaluation_dataset(tmp_path):
    """A repository root with a three-entry dataset in research/dataset/."""
    import hashlib

    directory = tmp_path / "research/dataset"
    (directory / "images").mkdir(parents=True)
    entries = []
    rows = [
        ("Required", "injection", "web_page", ["low_contrast"]),
        ("Missing target", "benign", "web_page", []),
        ("Failure target", "jailbreak", "text_image", []),
    ]
    for index, (text, label, content, obfuscation) in enumerate(rows):
        path = directory / f"images/{index}.png"
        Image.new("RGB", (16, 12), "white").save(path)
        entries.append(
            {
                "id": str(index),
                "image": f"images/{index}.png",
                "image_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "label": label,
                "techniques": [] if label == "benign" else ["task_redirection"],
                "goal": [],
                "obfuscation": obfuscation,
                "evidence": [],
                "content": content,
                "payload": None,
                "cases": [],
                "ocr_reference": {
                    "text": text,
                    "scope": "source_declared_text",
                    "quality": "silver",
                    "reading_order_known": True,
                    "regions": None,
                },
                "source": {"dataset": "fixture"},
            }
        )
    (directory / "catalog.json").write_text(json.dumps(entries))
    return tmp_path
