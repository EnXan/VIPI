import pytest

from vipi.ocr.recovery.resolution_retention import (
    insertion_retention,
    repair_resolution_reading,
)


def region(text, confidence, x=0):
    return {
        "text": text,
        "confidence": confidence,
        "input_polygon": [[x, 0], [x + 100, 0], [x + 100, 20], [x, 20]],
    }


def frequency(word):
    return {"partion": 1, "partition": 4, "requests": 4, "regquests": 0}.get(word, 0)


def test_retention_accepts_missing_letters_supported_by_same_image_region():
    result = insertion_retention(
        [region("partion", 0.95)],
        [region("partition", 0.99)],
        "partition",
        word_frequency=frequency,
    )
    assert result["missing"] == []
    assert [(r["old"], r["new"]) for r in result["corrections"]] == [
        ("partion", "partition")
    ]


@pytest.mark.parametrize(
    "old,new",
    [
        (region("partion", 0.99), region("partition", 0.98)),
        (region("partion", 0.99), region("partition", 0.99)),
        (region("partion", 0.95), region("partition", 0.99, 200)),
        (region("requests", 0.95), region("regquests", 0.99)),
        (region("partion", 0.95), region("portion", 0.99)),
        (region("I", 0.95), region("II", 0.99)),
        (region("418", 0.95), region("4181", 0.99)),
    ],
)
def test_retention_rejects_unsupported_corrections(old, new):
    result = insertion_retention([old], [new], new["text"], word_frequency=frequency)
    assert result["missing"]
    assert result["corrections"] == []


def test_one_candidate_cannot_repair_two_occurrences():
    result = insertion_retention(
        [region("partion", 0.95), region("partion", 0.95, 200)],
        [region("partition", 0.99)],
        "partition",
        word_frequency=frequency,
    )
    assert result["missing"] == ["partion"]
    assert len(result["corrections"]) == 1


def test_repair_preserves_content_not_present_in_candidate():
    old = region("partion", 0.95)
    untouched = region("rare identifier stays", 0.2, 200)
    groups = [dict(old), dict(untouched)]
    result = repair_resolution_reading(
        groups,
        [old, untouched],
        [region("partition", 0.99)],
        "partition",
        word_frequency=frequency,
    )
    assert result["text"] == "partition\nrare identifier stays"
    assert groups[0]["text"] == "partion"
    assert len(result["changes"]) == 1


def test_repair_refuses_ambiguous_group_mapping():
    old = region("partion", 0.95)
    result = repair_resolution_reading(
        [dict(old), dict(old)],
        [old],
        [region("partition", 0.99)],
        "partition",
        word_frequency=frequency,
    )
    assert result["changes"] == []
    assert result["text"] == "partion\npartion"
