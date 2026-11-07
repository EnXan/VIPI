"""Check the explicit scoring boundary of the transcription-only trial."""

from copy import deepcopy

from research.ocr_eval.experiments.luna_only import text_score


def reference(text, *, ordered=False):
    return {
        "text": text,
        "reading_order_known": ordered,
        "regions_are_independent": True,
        "regions": [
            {"text": word, "input_polygon": [[10, 10], [20, 10], [20, 20], [10, 20]]}
            for word in text.split()
        ],
    }


def test_unordered_transcripts_ignore_geometry_and_inter_region_order():
    source = reference("alpha beta gamma")
    before = deepcopy(source)
    result = text_score(source, "gamma beta alpha")
    assert result["valid"]
    assert result["exact"]["valid"]
    assert source == before


def test_repeated_words_still_require_distinct_observations():
    result = text_score(reference("alpha alpha alpha"), "alpha")
    assert result["matched"] == 1
    assert result["total"] == 3
    assert not result["valid"]


def test_known_order_remains_required():
    result = text_score(reference("alpha beta gamma", ordered=True), "gamma beta alpha")
    assert result["matched"] == 1


def test_tolerant_and_exact_fidelity_remain_separate():
    result = text_score(reference("Hello!"), "hello")
    assert result["valid"]
    assert result["exact"]["matched"] == 0


def test_empty_transcription_has_zero_credit():
    result = text_score(reference("alpha beta"), "")
    assert result["matched"] == 0
    assert not result["valid"]
