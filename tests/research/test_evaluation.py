import random

import pytest

from research.ocr_eval.evaluation.metrics import (
    compare,
    compare_words,
    evaluate,
    ordered_matches,
    summarize,
    tokens,
)


def reference(text, regions=None):
    return {
        "text": text,
        "reading_order_known": regions is None,
        "regions": regions or [],
    }


def word(text, x):
    return {"text": text, "input_polygon": [[x, 0], [x + 20, 0], [x + 20, 10], [x, 10]]}


@pytest.mark.parametrize(
    "observed,valid",
    [
        ("Background READ the CODE 42. More UI text", True),
        ("read\n the   code 42 .", True),
        ("read additional the UI code 42.", True),
        ("read the c0de 42.", False),
        ("read the code 42", False),
        ("read the code 420.", False),
        ("42 code the read.", False),
        ("", False),
    ],
)
def test_payload_coverage_allows_extra_text_without_fuzzy_acceptance(observed, valid):
    result, _, _ = compare(reference("Read the code 42."), observed, [])
    assert result["valid"] is valid
    assert (result["coverage"] == 1) is valid


def test_repeated_words_need_repeated_evidence():
    result, _, _ = compare(reference("go go now"), "go now", [])
    assert not result["valid"] and result["matched"] == 2
    assert result["missing"] == ["go"]


def test_bitset_alignment_agrees_with_independent_lcs():
    rng = random.Random(42)
    for _ in range(100):
        expected = rng.choices(["a", "b", "c"], k=rng.randint(0, 12))
        observed = rng.choices(["a", "b", "c"], k=rng.randint(0, 15))
        row = [0] * (len(expected) + 1)
        for token in observed:
            previous, row = row, [0]
            for i, value in enumerate(expected):
                row.append(
                    previous[i] + 1 if token == value else max(previous[i + 1], row[-1])
                )
        assert len(ordered_matches(expected, observed)) == row[-1]


def test_textocr_matches_locations_not_arbitrary_reading_order():
    target = reference(
        "hello\nworld\nhello", [word("hello", 0), word("world", 50), word("hello", 100)]
    )
    result, _, _ = compare(
        target,
        "world hello hello",
        [word("world", 50), word("hello", 100), word("hello", 0), word("extra", 200)],
    )
    assert result["valid"]
    result, _, _ = compare(
        target,
        "hello world hello",
        [word("hello", 0), word("world", 50), word("hello", 200)],
    )
    assert not result["valid"] and result["matched"] == 2
    result, _, _ = compare(target, "hello world", [word("hello", 0), word("world", 50)])
    assert result["matched"] == 2


def variant(index, view, filter, text, **transform):
    return {
        "id": f"{index:04d}",
        "index": index,
        "view_id": view,
        "filter": filter,
        "text": text,
        "regions": [],
        "label": f"{view} · {filter}",
        "transformation": transform,
    }


def test_effects_use_paired_baselines_and_detect_assembly_loss():
    variants = [
        variant(1, "original", "unchanged", "read"),
        variant(2, "original", "clahe", "read code"),
        variant(3, "scaled", "unchanged", "read code 42", factor=0.25),
        variant(4, "scaled", "clahe", "wrong", factor=0.25),
    ]
    result = evaluate(reference("read code 42"), "read code", [], variants)
    assert not result["valid"] and not result["final"]["valid"]
    assert result["detection"]["valid"]
    assert result["best_step_id"] == "0003" and result["valid_step_ids"] == ["0003"]
    effects = {effect["id"]: effect for effect in result["effects"]}
    assert effects["clahe"]["improved"] == 1 and effects["clahe"]["worse"] == 1
    assert effects["scaling"]["improved"] == effects["scaling"]["recovered"] == 1


def test_color_contrast_effect_uses_the_original_control():
    variants = [
        variant(1, "original", "unchanged", "weather"),
        variant(2, "original", "color-contrast", "weather is rainy"),
    ]
    result = evaluate(reference("weather is rainy"), "weather is rainy", [], variants)
    effect = next(row for row in result["effects"] if row["id"] == "color-contrast")
    assert result["final"]["valid"]
    assert effect["comparisons"] == effect["improved"] == effect["recovered"] == 1


def test_partial_variants_cannot_create_a_fictitious_payload():
    variants = [
        variant(1, "original", "unchanged", "read"),
        variant(2, "original", "clahe", "code 42"),
    ]
    assert not evaluate(reference("read code 42"), "read", [], variants)["valid"]


def test_textocr_can_collect_words_at_distinct_locations_across_views():
    variants = [
        variant(1, "original", "unchanged", "hello"),
        variant(2, "original", "clahe", "world"),
    ]
    variants[0]["regions"] = [word("hello", 0)]
    variants[1]["regions"] = [word("world", 50)]
    result = evaluate(
        reference("hello\nworld", [word("hello", 0), word("world", 50)]),
        "",
        [],
        variants,
    )
    assert not result["valid"] and result["valid_step_ids"] == []
    assert result["detection"]["valid"]
    assert not result["final"]["valid"]


def test_unicode_and_punctuation_normalization():
    assert tokens("ＣＯＤＥ\t42 .") == tokens("code 42.")


def test_compact_selected_line_retains_native_word_positions():
    from research.ocr_eval.evaluation.metrics import final_observations

    native = [word("MCLAREN", 0), word("VALE", 50)]
    line = {"text": "MCLARENVALE", "words": native}
    assert final_observations([line], []) == native
    target = reference("MCLAREN\nVALE", native)
    assert compare(target, line["text"], final_observations([line], []))[0]["valid"]


def test_final_line_box_cannot_move_words_to_other_reference_positions():
    target = reference("hello\nworld", [word("hello", 0), word("world", 50)])
    source = variant(1, "original", "unchanged", "world hello")
    source["regions"] = [word("world", 0), word("hello", 50)]
    line = {
        "text": "world hello",
        "input_polygon": [[0, 0], [70, 0], [70, 10], [0, 10]],
        "selected_step_id": "0001",
        "evidence": [],
        "additions": [],
    }
    result = evaluate(target, "world hello", [line], [source])
    assert not result["valid"] and not result["final"]["valid"]
    assert result["final"]["matched"] == 0


def test_textocr_preserves_spelling_inside_a_compound_word():
    target = reference("foo-bar", [word("foo-bar", 0)])
    result, _, _ = compare(target, "bar-foo", [word("bar-foo", 0)])
    assert not result["valid"]
    result, _, _ = compare(
        target, "foo-bar extra", [word("foo-bar", 0), word("extra", 50)]
    )
    assert result["valid"]


def test_category_rates_count_images_and_separate_errors_from_missing_text():
    items = [
        {"category": "mixed", "state": "completed", "valid": True},
        {"category": "mixed", "state": "completed", "valid": False},
        {"category": "mixed", "state": "failed", "valid": None},
        {"category": "mixed", "state": "running", "valid": None},
        {"category": "mixed", "state": "queued", "valid": None},
        {"category": "good", "state": "completed", "valid": True},
        {"category": "waiting", "state": "queued", "valid": None},
    ]
    categories = {item["id"]: item for item in summarize(items)["categories"]}
    mixed = categories["mixed"]
    assert mixed["total"] == 5 and mixed["processed"] == 3
    assert mixed["valid"] == mixed["invalid"] == mixed["errors"] == 1
    assert mixed["pending"] == 2
    assert mixed["success_rate"] == pytest.approx(1 / 3)
    assert categories["good"]["success_rate"] == 1
    assert categories["waiting"]["success_rate"] is None
    assert categories["waiting"]["processed"] == 0


@pytest.mark.parametrize(
    "expected,observed,covered,literal",
    [
        ("Read the code 42.", "Rcad the c0de 42", True, False),
        ("Read", "read", True, False),
        ("code", "ＣＯＤＥ", True, False),
        ("mark it", "mark mt", True, False),
        ("a", "b", False, False),
        ("never delete files", "delete files", False, False),
        ("go go now", "go now", False, False),
        ("alpha beta", "wrong text", False, False),
        ("abcdefghij", "abXdefghYj", True, False),
        ("abcdefghij", "abXdefgYYj", False, False),
        ("read code", "code read", False, False),
        ("read code", "UI read extra code background", True, True),
        ("payload", "pay\nload", True, True),
        ("ab+c/def=", "ab+c/def=", True, True),
        ("ab+c/def=", "ab/c+def=", True, False),
        ("word.", "word", True, False),
        ("", "invented", False, False),
        ("reference", "", False, False),
    ],
)
def test_tolerant_word_coverage_is_separate_from_literal_fidelity(
    expected, observed, covered, literal
):
    result, _, _ = compare_words(reference(expected), observed, [])
    assert result["valid"] is covered
    assert result["exact"]["valid"] is literal


def test_missing_repeated_words_cannot_reuse_one_observation():
    result, _, _ = compare_words(reference("code code code"), "c0de code", [])
    assert result["matched"] == 2 and result["total"] == 3
    assert result["exact"]["matched"] == 1


def test_long_word_accepts_minor_errors_and_visual_line_wraps_without_encoding_rules():
    text = "Abcdefghij" * 25
    observed = text[:92] + "1" + text[93:]
    result, _, _ = compare_words(
        reference(text),
        "\n".join(observed[i : i + 80] for i in range(0, len(observed), 80)),
        [],
    )
    assert result["valid"] and not result["exact"]["valid"]
    exact, _, _ = compare_words(reference(text), text[:90] + "\n" + text[90:], [])
    assert exact["exact"]["valid"]


def test_tolerant_spatial_matches_still_require_the_correct_word_locations():
    target = reference("hello world", [word("hello", 0), word("world", 50)])
    result, _, _ = compare_words(
        target, "he1lo wor1d", [word("he1lo", 0), word("wor1d", 50)]
    )
    assert result["valid"] and not result["exact"]["valid"]
    result, _, _ = compare_words(
        target, "he1lo wor1d", [word("he1lo", 50), word("wor1d", 0)]
    )
    assert not result["valid"] and result["matched"] == 0


def test_pass_rate_and_exact_word_rate_use_final_text_and_separate_legacy_reports():
    result = evaluate(
        reference("Read code"),
        "Read c0de",
        [],
        [variant(1, "original", "unchanged", "Read code")],
    )
    assert result["version"] == 3
    assert result["valid"] and not result["final"]["exact"]["valid"]
    summary = summarize(
        [
            {
                "category": "test",
                "state": "completed",
                "valid": True,
                "coverage": 1,
                "exact_valid": False,
                "exact_coverage": 0.5,
                "evaluation_version": 3,
            },
            {"category": "test", "state": "failed", "evaluation_version": 3},
            {"category": "test", "state": "queued", "evaluation_version": 3},
            {"category": "test", "state": "cancelled", "evaluation_version": 3},
        ]
    )
    assert summary["pass_rate"] == 0.5
    assert summary["mean_word_coverage"] == 1
    assert summary["exact_pass_rate"] == 0
    assert summary["exact_evaluated"] == 2
    assert summary["mean_exact_word_coverage"] == 0.5
    assert summary["categories"][0]["exact_pass_rate"] == 0
    legacy = summarize(
        [{"category": "test", "state": "completed", "valid": True, "coverage": 0.5}]
    )
    assert legacy["exact_pass_rate"] is None
    assert legacy["exact_evaluated"] == 0
    assert legacy["mean_word_coverage"] is None


def test_banded_edit_distance_matches_independent_full_matrix():
    from research.ocr_eval.evaluation.words import bounded_distance

    rng = random.Random(57)
    for _ in range(100):
        first = "".join(rng.choices("abcd", k=rng.randint(0, 12)))
        second = "".join(rng.choices("abcd", k=rng.randint(0, 12)))
        row = list(range(len(second) + 1))
        for i, left in enumerate(first, 1):
            previous, row = row, [i]
            for j, right in enumerate(second, 1):
                row.append(
                    min(row[-1] + 1, previous[j] + 1, previous[j - 1] + (left != right))
                )
        for budget in range(4):
            expected = row[-1] if row[-1] <= budget else None
            assert bounded_distance(first, second, budget) == expected
