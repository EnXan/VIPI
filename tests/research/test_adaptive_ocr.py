import json

import numpy as np
from PIL import Image
import pytest

from research.ocr_eval.evaluation import adaptive
from research.ocr_eval.evaluation.layout import group_reading
from research.ocr_eval.evaluation.transform_decisions import (
    JevDecider,
    decision_preview,
    plan_catalog,
    plan_questions,
    read_choice,
)
from vipi.ocr.measured_transforms import ORIENTATIONS, orientation_view
from vipi.ocr.transforms import render_view
from vipi.storage.ocr import RunStore


def answer(label):
    return {
        "type": "choice",
        "choice": label,
        "confidence": 0.8,
        "probabilities": {label: 1.0},
    }


def response(plan="upright|unchanged|full", action=None, best="0001"):
    answers = {"plan": answer(plan)}
    if action:
        answers.update(action=answer(action), best_attempt=answer(best))
    return {
        "response": {"model": "fake-jev", "answers": answers},
        "elapsed_seconds": 0.01,
    }


class Decider:
    model = "fake-jev"

    def __init__(self, responses):
        self.responses = iter(responses)
        self.history = []

    def decide(self, original, attempts, directory):
        self.history.append(
            [{k: a[k] for k in ("id", "plan", "text")} for a in attempts]
        )
        return next(self.responses)


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


def test_three_attempts_restart_from_original_and_can_select_earlier_candidate(
    tmp_path,
):
    source = tmp_path / "input.png"
    original = np.full((300, 400, 3), (15, 60, 120), dtype=np.uint8)
    Image.fromarray(original).save(source)
    decider = Decider(
        [
            response(),
            response("upright|inverted|full", "retry"),
            response("upright|blue-channel|full", "retry", "0001"),
            response(action="accept", best="0002"),
        ]
    )
    engine = Engine()
    result = adaptive.extract(
        source,
        "ppocr-v6-tiny",
        engine=engine,
        decider=decider,
        runs_dir=tmp_path / "runs",
    )
    assert np.array_equal(engine.rasters[0], original)
    assert np.array_equal(engine.rasters[1], 255 - original)
    assert (engine.rasters[2] == 120).all()
    assert result["text"] == "candidate2"
    assert result["selection"]["selected_attempt"] == "0002"
    assert result["selection"]["accepted"] is True
    assert len(decider.history[-1]) == 3
    directory = tmp_path / "runs" / result["run_id"]
    assert (directory / "result.txt").read_text() == result["text"]
    snapshot = RunStore.restore(directory).snapshot()
    assert snapshot["completed"] == snapshot["total"] == 3
    assert len(snapshot["variants"]) == 3
    assert (
        json.loads((directory / "attempts.json").read_text())[2]["review"][
            "best_attempt"
        ]
        == "0002"
    )


@pytest.mark.parametrize(
    "final_action,reason", [("retry", "attempt_limit"), ("uncertain", "uncertain")]
)
def test_incomplete_results_are_never_accepted(tmp_path, final_action, reason):
    source = tmp_path / "input.png"
    Image.new("RGB", (400, 300), "white").save(source)
    decider = Decider(
        [
            response(),
            response("upright|inverted|full", "retry"),
            response("upright|blue-channel|full", "retry"),
            response(action=final_action),
        ]
    )
    result = adaptive.extract(
        source,
        "ppocr-v6-tiny",
        engine=Engine(),
        decider=decider,
        runs_dir=tmp_path / "runs",
    )
    assert result["selection"]["accepted"] is False
    assert result["selection"]["stop_reason"] == reason
    assert len(result["variants"]) == 3


def test_retry_choices_exclude_complete_previous_plans():
    used = {"orientation": "upright", "contrast": "unchanged", "crop": "full"}
    available = plan_questions([{"plan": used}])["plan"]["criteria"]
    assert "upright|unchanged|full" not in available
    assert "upright|inverted|full" in available
    assert len(available) == len(plan_catalog()) - 1


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


def test_research_profile_evaluates_selected_attempt_without_inventing_original(
    tmp_path,
):
    from research.ocr_eval.evaluation.runner import extract

    source = tmp_path / "input.png"
    Image.new("RGB", (400, 300), "white").save(source)
    decider = Decider([response("upright|clahe-lab|full"), response(action="accept")])
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
    assert result["evaluation"]["original"] is None
    assert result["evaluation"]["first_attempt"]["valid"] is True
    assert result["evaluation"]["effects"] == []
    assert result["cost"]["estimated_usd"] is None


def test_decision_failure_keeps_saved_ocr_without_completed_result(tmp_path):
    source = tmp_path / "input.png"
    Image.new("RGB", (400, 300), "white").save(source)
    store = RunStore(tmp_path / "runs", "ppocr-v6-tiny")
    with pytest.raises(StopIteration):
        adaptive.extract(
            source,
            "ppocr-v6-tiny",
            engine=Engine(),
            decider=Decider([response()]),
            store=store,
        )
    assert store.snapshot()["state"] == "failed"
    assert len(store.snapshot()["variants"]) == 1
    assert not (store.directory / "result.json").exists()


def test_requests_use_only_images_ocr_and_plans_not_dataset_references(
    tmp_path, monkeypatch
):
    import research.ocr_eval.evaluation.transform_decisions as module

    sent = []

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self):
            return json.dumps(response()["response"]).encode()

    def urlopen(request, **options):
        sent.append(json.loads(request.data))
        return Connection()

    monkeypatch.setattr(module, "api_key", lambda *args: "fake-key")
    monkeypatch.setattr(module.urllib.request, "urlopen", urlopen)
    JevDecider().decide(Image.new("RGB", (3200, 3200)), [], tmp_path / "decision")
    payload = sent[0]
    assert set(payload["state"]) == {"task", "original_image"}
    saved = (tmp_path / "decision" / "request.json").read_text()
    assert "fake-key" not in saved
    assert "data_base64" not in saved
    assert (tmp_path / "decision" / "original-image.png").exists()
