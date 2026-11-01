import pytest

from research.ocr_eval.evaluation.code_integrity import code_disagreements


def group(text, x=0):
    return {
        "text": text,
        "input_polygon": [[x, 0], [x + 100, 0], [x + 100, 10], [x, 10]],
    }


def test_flags_long_code_disagreement_at_same_location():
    old = group("UmVwbGF5IHRyYWZmaWMgaXMgZXhwZWN0ZWQ=")
    new = group("UmVwbGF5IHRyYWZmaWMgaXMgZXhwZWN0ZW8=")
    assert len(code_disagreements([old], [new])) == 1


def test_ignores_short_ordinary_text_and_nonoverlapping_regions():
    assert not code_disagreements([group("ordinary")], [group("different")])
    assert not code_disagreements([group("a" * 30)], [group("b" * 30, x=200)])


def test_missing_geometry_is_unavailable():
    with pytest.raises(ValueError, match="Primary group geometry unavailable"):
        code_disagreements([{"text": "A" * 30}], [group("A" * 30)])
