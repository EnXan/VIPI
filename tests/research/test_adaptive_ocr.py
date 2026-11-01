import numpy as np
from PIL import Image
import pytest

from research.ocr_eval.evaluation import adaptive
from research.ocr_eval.evaluation.layout import group_reading
from research.ocr_eval.evaluation.transform_decisions import (
    DecisionsDecider,
    decision_preview,
    read_choice,
)
from vipi.ocr.measured_transforms import ORIENTATIONS, orientation_view
from vipi.ocr.transforms import render_view
from vipi.storage.ocr import RunStore


def test_research_and_product_execute_the_same_recovery_code():
    from vipi.ocr import adaptive as product

    assert adaptive is product


def answer(label):
    return {
        "type": "choice",
        "choice": label,
        "confidence": 0.8,
        "probabilities": {label: 1.0},
    }


class Decider:
    model = "fake-decisions"
    provider = "fake"

    def __init__(
        self, outcomes=None, engine=None, assessment="ready", orientation="mirror-180"
    ):
        self.outcomes = outcomes or {}
        self.engine = engine
        self.assessment = assessment
        self.orientation = orientation
        self.history = []
        self.gates = 0
        self.orientation_calls = 0

    def assess(self, original, attempt, directory):
        self.gates += 1
        if self.engine is not None:
            assert len(self.engine.rasters) == 1
        return {"response": {"answers": {"assessment": answer(self.assessment)}}}

    def choose_orientation(self, original, directory):
        self.orientation_calls += 1
        return self.orientation, {
            "response": {"answers": {"orientation": answer(self.orientation)}}
        }

    def compare(self, original, incumbent, candidate, directory):
        self.history.append((incumbent["id"], candidate["id"]))
        outcome = self.outcomes.get(candidate["id"], "equivalent")
        return {"response": {"answers": {"comparison": answer(outcome)}}}


class Engine:
    def __init__(self):
        self.rasters = []

    def recognize(self, image):
        self.rasters.append(np.asarray(image).copy())
        text = f"candidate{len(self.rasters)}"
        return {
            "text": text,
            "regions": [
                {
                    "text": text,
                    "confidence": 0.9,
                    "polygon": [[20, 20], [150, 20], [150, 40], [20, 40]],
                }
            ],
        }


class EmptyEngine:
    def recognize(self, image):
        return {"text": "", "regions": []}


@pytest.mark.parametrize("orientation", ORIENTATIONS)
@pytest.mark.parametrize(
    "crop", ["full", "center-half", "center-quarter", "center-75x50", "center-50x50"]
)
def test_orientation_crop_pixels_map_back_to_original(orientation, crop):
    pixels = np.arange(32 * 48, dtype=np.uint16).reshape(32, 48)
    image = Image.fromarray(pixels)
    plan = {"orientation": orientation, "crop": crop}
    view = adaptive.view_for_plan(image.size, plan)
    rendered = np.asarray(render_view(image, view))
    assert rendered.shape == (view.height, view.width)
    for y, x in [
        (0, 0),
        (view.height // 2, view.width // 2),
        (view.height - 1, view.width - 1),
    ]:
        sx, sy = view.map_polygon([(x + 0.5, y + 0.5)])[0]
        assert rendered[y, x] == pixels[int(sy), int(sx)]


def test_layout_orders_in_corrected_frame_then_maps_boxes():
    view = orientation_view(400, 300, "mirror-180")
    regions = [
        {
            "text": text,
            "confidence": 0.95,
            "polygon": [[20, y], [150, y], [150, y + 20], [20, y + 20]],
        }
        for text, y in [("First sentence", 20), ("Second sentence", 220)]
    ]
    step = {
        "id": "0001",
        "width": 400,
        "height": 300,
        "text": "First sentence\nSecond sentence",
        "regions": regions,
    }
    text, groups = group_reading(step, Image.new("RGB", (400, 300), "white"), view)
    assert text == "First sentence\nSecond sentence"
    assert groups[0]["input_polygon"][0][1] > groups[1]["input_polygon"][0][1]
    assert "input_polygon" not in regions[0]  # No mutation of native observations.


def test_ready_original_keeps_selected_reading_after_guarded_resolution_probes(
    tmp_path,
):
    source = tmp_path / "input.png"
    Image.new("RGB", (400, 300), "white").save(source)
    engine = Engine()
    decider = Decider(engine=engine)
    result = adaptive.extract(
        source,
        "ppocr-v6-tiny",
        engine=engine,
        decider=decider,
        runs_dir=tmp_path / "runs",
    )
    assert len(engine.rasters) == 3
    assert decider.gates == 1
    assert len(result["selection"]["decisions"]) == 2
    assert decider.history == [("0001", "0002")]
    assert decider.orientation_calls == 0
    assert result["selection"]["stop_reason"] == "original_ready"


def test_contrast_attempt_starts_from_original_and_stops_on_first_improvement(tmp_path):
    source = tmp_path / "input.png"
    original = np.full((300, 400, 3), (15, 60, 120), dtype=np.uint8)
    Image.fromarray(original).save(source)
    engine = Engine()
    decider = Decider({"0002": "improved"}, engine=engine, assessment="contrast")
    result = adaptive.extract(
        source,
        "ppocr-v6-tiny",
        engine=engine,
        decider=decider,
        runs_dir=tmp_path / "runs",
    )
    assert np.array_equal(engine.rasters[0], original)
    assert (engine.rasters[1] == 45).all()
    assert len(engine.rasters) == 3
    assert result["text"] == "candidate2"
    assert len(result["selection"]["decisions"]) == 2
    snapshot = RunStore.restore(tmp_path / "runs" / result["run_id"]).snapshot()
    assert snapshot["completed"] == snapshot["total"] == 3


@pytest.mark.parametrize("outcome", ["equivalent", "worse", "uncertain"])
def test_unverified_corrections_keep_original(tmp_path, outcome):
    source = tmp_path / "input.png"
    Image.new("RGB", (400, 300), "white").save(source)
    decider = Decider({f"{i:04d}": outcome for i in range(2, 5)}, assessment="contrast")
    result = adaptive.extract(
        source,
        "ppocr-v6-tiny",
        engine=Engine(),
        decider=decider,
        runs_dir=tmp_path / "runs",
    )
    assert result["text"] == "candidate1"
    assert result["selection"]["accepted"] is False
    assert len(result["variants"]) == 6


def test_empty_ocr_uses_local_probes_without_paying_for_empty_comparisons(tmp_path):
    source = tmp_path / "input.png"
    Image.new("RGB", (400, 300), "white").save(source)
    decider = Decider()
    result = adaptive.extract(
        source,
        "ppocr-v6-tiny",
        engine=EmptyEngine(),
        decider=decider,
        runs_dir=tmp_path / "runs",
    )
    assert len(result["variants"]) == 4
    assert len(result["selection"]["decisions"]) == decider.gates == 1
    assert not decider.history
    assert result["selection"]["accepted"] is False


def test_orientation_route_recognizes_only_selected_orientation(tmp_path):
    source = tmp_path / "input.png"
    Image.new("RGB", (400, 300), "white").save(source)
    decider = Decider({"0002": "improved"}, assessment="orientation")
    result = adaptive.extract(
        source,
        "ppocr-v6-tiny",
        engine=Engine(),
        decider=decider,
        runs_dir=tmp_path / "runs",
    )
    assert len(result["variants"]) == 3
    assert result["variants"][1]["plan"]["orientation"] == "mirror-180"
    assert decider.orientation_calls == 1
    assert len(result["selection"]["decisions"]) == 3


@pytest.mark.parametrize(
    "size", [(3200, 3200), (4368, 4368), (760, 760), (1600, 40), (40, 40)]
)
def test_jev_preview_meets_documented_dimensions(size):
    image = Image.new("RGB", size)
    preview = decision_preview(image)
    assert all(280 <= side <= 1568 for side in preview.size)
    assert image.size == size


def test_invalid_or_missing_confidence_is_not_silently_accepted():
    with pytest.raises(ValueError, match="confidence"):
        read_choice(
            {"answers": {"action": {"type": "choice", "choice": "accept"}}},
            "action",
            ["accept"],
        )


def test_pair_comparison_sends_real_ocr_and_keep_options(tmp_path, monkeypatch):
    payloads = []

    def transport(url, key, payload, **options):
        payloads.append(payload)
        return {
            "answers": [{"name": "comparison", **answer("uncertain")}],
            "usage": {},
        }, {}

    monkeypatch.setenv("OPENAI_API_KEY", "fixture-key")
    image = Image.new("RGB", (900, 600), "white")
    attempt = {
        "id": "0001",
        "raster": image,
        "text": "Keep WORD 42",
        "groups": [],
        "step": {"regions": [{"polygon": [[10, 10], [200, 10], [200, 30], [10, 30]]}]},
    }
    DecisionsDecider(transport=transport).compare(
        image,
        attempt,
        {**attempt, "id": "0002", "text": "Keep WORD42"},
        tmp_path / "pair",
    )
    payload = payloads[0]
    assert {choice["value"] for choice in payload["questions"][0]["choices"]} == {
        "improved",
        "equivalent",
        "worse",
        "uncertain",
    }
    text = payload["input"][0]["content"][0]["text"]
    assert "Keep WORD 42" in text and "Keep WORD42" in text
    assert "detected_text_crop" in text
    assert "candidate" in text and "incumbent" in text
    images = [
        part for part in payload["input"][0]["content"] if part["type"] == "input_image"
    ]
    assert images and all(
        part["image_url"].startswith("data:image/jpeg;base64,") for part in images
    )
    saved = (tmp_path / "pair" / "request.json").read_text()
    assert "fixture-key" not in saved and "data:image/" not in saved


def test_adaptive_cost_never_reports_zero_for_unpriced_jev_calls():
    from research.workbench.ocr_costs import cost_for_result

    cost = cost_for_result(
        {
            "model": "ppocr-v6-tiny",
            "selection": {
                "decisions": [
                    {"response": {"usage": {"input_tokens": 100, "output_tokens": 20}}}
                ]
            },
        }
    )
    assert cost["estimated_usd"] is None
    assert cost["ocr"]["estimated_usd"] == 0
    assert cost["usage"] == [{"input_tokens": 100, "output_tokens": 20}]


def test_adaptive_cost_includes_each_staged_preview_request():
    from research.workbench.ocr_costs import cost_for_result

    cost = cost_for_result(
        {
            "model": "ppocr-v6-tiny",
            "selection": {
                "provider": "openai-decisions",
                "decisions": [
                    {
                        "response": {"usage": {"input_tokens": 30}},
                        "records": [
                            {
                                "response": {"usage": {"input_tokens": 10}},
                                "estimated_usd": 0.01,
                            },
                            {
                                "response": {"usage": {"input_tokens": 20}},
                                "estimated_usd": 0.02,
                            },
                        ],
                    }
                ],
            },
        }
    )
    assert cost["usage"] == [
        {"input_tokens": 10},
        {"input_tokens": 20},
    ]
    assert cost["estimated_usd"] == 0.03


def test_research_profile_evaluates_selected_attempt_without_inventing_original(
    tmp_path,
):
    from research.ocr_eval.evaluation.runner import extract

    source = tmp_path / "input.png"
    Image.new("RGB", (400, 300), "white").save(source)
    decider = Decider()
    result = extract(
        source,
        "ppocr-v6-tiny",
        ocr_profile="adaptive-jev",
        engine=Engine(),
        decider=decider,
        reference={"text": "candidate1", "reading_order_known": True, "regions": []},
        runs_dir=tmp_path / "runs",
    )
    assert result["evaluation"]["valid"] is True
    assert result["evaluation"]["original"]["valid"] is True
    assert result["evaluation"]["first_attempt"]["valid"] is True
    assert result["evaluation"]["effects"] == []
    assert result["cost"]["estimated_usd"] is None


def test_decision_failure_keeps_saved_ocr_without_completed_result(tmp_path):
    source = tmp_path / "input.png"
    Image.new("RGB", (400, 300), "white").save(source)
    store = RunStore(tmp_path / "runs", "ppocr-v6-tiny")

    class FailingDecider(Decider):
        def compare(self, *args):
            raise RuntimeError("Provider unavailable")

    with pytest.raises(RuntimeError, match="Provider unavailable"):
        adaptive.extract(
            source,
            "ppocr-v6-tiny",
            engine=Engine(),
            decider=FailingDecider(assessment="contrast"),
            store=store,
        )
    assert store.snapshot()["state"] == "failed"
    assert len(store.snapshot()["variants"]) == 2
    assert not (store.directory / "result.json").exists()
