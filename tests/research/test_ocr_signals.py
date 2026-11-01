import pytest

from research.ocr_eval.evaluation import signals


@pytest.mark.parametrize("strategy", ["priority_cascade", "any_signal", "corroborated"])
def test_empty_ocr_is_inspected_without_reference(strategy):
    result = signals.route("", [], [], strategy)
    assert result["route"] == "inspect"
    assert result["signals"][0]["name"] == "empty_text"


def test_priority_cascade_does_not_load_linguistic_evidence_for_empty_text(monkeypatch):
    def unavailable(_):
        raise AssertionError("Linguistic model should not run")

    monkeypatch.setattr(signals, "_known_word", unavailable)
    result = signals.route("", [], [], "priority_cascade")
    assert [signal["name"] for signal in result["signals"]] == ["empty_text"]


def test_corroboration_requires_both_weak_groups(monkeypatch):
    monkeypatch.setattr(signals, "_known_word", lambda word: True)
    text = "This sufficiently long text contains several ordinary words for this test"
    regions = [{"confidence": 0.4}, {"confidence": 0.5}]
    assert signals.route(text, regions, [], "any_signal")["route"] == "inspect"
    assert signals.route(text, regions, [], "corroborated")["route"] == "no_signal"
    monkeypatch.setattr(signals, "_known_word", lambda word: False)
    assert signals.route(text, regions, [], "corroborated")["route"] == "inspect"


def test_missing_evidence_is_not_clean(monkeypatch):
    monkeypatch.setattr(signals, "_known_word", lambda word: None)
    text = "This sufficiently long text contains several words with unavailable language evidence"
    result = signals.route(text, [], [], "any_signal")
    assert result["route"] == "unresolved"
    assert set(result["unavailable"]) == {"low_confidence", "unknown_words"}


def test_mixed_numeric_identifier_is_not_dictionary_word(monkeypatch):
    checked = []
    monkeypatch.setattr(
        signals, "_known_word", lambda word: checked.append(word) or True
    )
    text = "Several normal words here with BLUE42 and B19 included in this document"
    signals.route(text, [{"confidence": 0.99}], [], "any_signal")
    assert "blue" not in checked and "b" not in checked


def test_missing_cjk_tokenizers_make_word_evidence_unavailable(monkeypatch):
    signals._known_word.cache_clear()
    monkeypatch.setattr(signals, "find_spec", lambda name: None)
    try:
        assert signals._known_word("漢字") is None
    finally:
        signals._known_word.cache_clear()
