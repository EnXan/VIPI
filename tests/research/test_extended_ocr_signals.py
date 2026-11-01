import numpy as np
from PIL import Image

from research.ocr_eval.evaluation.extended_signals import (
    ExtendedParameters,
    additional_evidence,
    route_extended,
)


def region(text, confidence, box):
    x1, y1, x2, y2 = box
    return {
        "text": text,
        "confidence": confidence,
        "input_polygon": [[x1, y1], [x2, y1], [x2, y2], [x1, y2]],
    }


def by_name(text, regions, groups, image=None):
    return {
        signal.name: signal
        for signal in additional_evidence(text, regions, groups, image)
    }


def test_one_weak_region_can_trigger_despite_strong_page_average():
    regions = [region("hello", 0.99, (0, 0, 20, 20))] * 9 + [
        region("wrong", 0.2, (20, 0, 40, 20))
    ]
    assert (
        by_name("ordinary text", regions, [])["low_region_confidence"].state
        == "triggered"
    )


def test_small_and_low_contrast_regions_are_reported():
    image = Image.fromarray(np.full((40, 40), 128, dtype=np.uint8))
    result = by_name("hello world", [region("hello", 0.99, (0, 0, 20, 10))], [], image)
    assert result["small_text"].state == "triggered"
    assert result["low_region_contrast"].state == "triggered"


def test_missing_boxes_and_image_are_unavailable():
    result = by_name(
        "normal ordinary words", [{"text": "normal", "confidence": 0.99}], []
    )
    assert result["small_text"].state == "unavailable"
    assert result["low_region_contrast"].state == "unavailable"


def test_overlapping_groups_and_symbols_are_independent():
    result = by_name("!@#%^&**", [], [{"box": [0, 0, 20, 20]}, {"box": [5, 5, 15, 15]}])
    assert result["unusual_symbols"].state == "triggered"
    assert result["overlapping_groups"].state == "triggered"


def test_early_signal_short_circuits_extended_work():
    result = route_extended("", [], [])
    assert result["route"] == "inspect"
    assert [item["name"] for item in result["signals"]] == ["empty_text"]


def test_disabled_signals_do_not_trigger_or_create_unavailable_evidence():
    params = ExtendedParameters(regional_confidence=None, group_overlap=None)
    results = list(additional_evidence("ordinary text", [], [], None, params))
    names = {signal.name for signal in results}
    assert "low_region_confidence" not in names
    assert "overlapping_groups" not in names
