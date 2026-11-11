import random

import pytest

from research.ocr_eval.evaluation.metrics import (
    compare_words,
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


def test_unicode_and_punctuation_normalization():
    assert tokens("ＣＯＤＥ\t42 .") == tokens("code 42.")


def test_compact_selected_line_retains_native_word_positions():
    from research.ocr_eval.evaluation.metrics import final_observations

    native = [word("MCLAREN", 0), word("VALE", 50)]
    line = {"text": "MCLARENVALE", "words": native}
    assert final_observations([line], []) == native
    target = reference("MCLAREN\nVALE", native)
    assert compare_words(target, line["text"], final_observations([line], []))[0][
        "valid"
    ]


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
    from research.ocr_eval.benchmark_report import score_result

    result = score_result(
        target, {"text": "world hello", "regions": [line], "variants": [source]}
    )
    assert not result["valid"]
    assert result["matched"] == 0


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


def test_word_regions_ignore_group_order_but_preserve_words_within_a_group():
    regions = [word("Heading first", 0), word("Body second", 100)]
    target = reference("Heading first Body second", regions)
    target["regions_are_independent"] = True

    result, _, _ = compare_words(
        target,
        "Body second\nHeading first",
        [word("Body second", 100), word("Heading first", 0)],
    )
    assert result["valid"]

    result, _, _ = compare_words(
        target,
        "first Heading\nBody second",
        [word("first Heading", 0), word("Body second", 100)],
    )
    assert not result["valid"]


def test_observations_spanning_independent_groups_cannot_reassemble_them():
    def boxed_region(text, box):
        x1, y1, x2, y2 = box
        return {
            "text": text,
            "input_polygon": [[x1, y1], [x2, y1], [x2, y2], [x1, y2]],
        }

    target = {
        "text": "PROCUREMENT ASSISTANT GUIDANCE The SOC 2 renewal Type II",
        "reading_order_known": False,
        "regions": [
            boxed_region("PROCUREMENT ASSISTANT GUIDANCE", (0, 0, 100, 40)),
            boxed_region("The SOC 2 renewal Type II", (120, 0, 320, 40)),
        ],
        "regions_are_independent": True,
    }
    observations = [
        boxed_region("PROCUREMENT The SOC 2 renewal Type l", (0, 0, 320, 20)),
        boxed_region("ASSISTANT GUIDANCE", (0, 20, 320, 40)),
    ]

    result, _, _ = compare_words(
        target, " ".join(item["text"] for item in observations), observations
    )

    assert not result["valid"]
    assert result["group_conflicts"]


def test_single_letter_l_does_not_cover_double_i():
    target = {
        "text": "SOC 2 Type II",
        "reading_order_known": False,
        "regions": [word("SOC 2 Type II", 0)],
        "regions_are_independent": True,
    }
    result, _, _ = compare_words(
        target,
        "SOC 2 Type l",
        [word("SOC 2 Type l", 0)],
    )

    assert not result["valid"]
    assert result["missing"] == ["II"]


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
