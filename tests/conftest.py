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
def dataset_repository(tmp_path):
    directory = tmp_path / "research/ocr_eval"
    directory.mkdir(parents=True)
    image_root = directory / "images"
    image_root.mkdir(parents=True)
    records = []
    for i, text in enumerate(["Required", "Missing target", "Failure target"]):
        path = image_root / f"{i}.png"
        Image.new("RGB", (16, 12), "white").save(path)
        records.append(
            {
                "image": path.relative_to(image_root.parent).as_posix(),
                "text": text,
                "category": "vpi_bench" if i < 2 else "mm_safetybench",
            }
        )
    (directory / "catalog.json").write_text(json.dumps(records))
    return tmp_path
