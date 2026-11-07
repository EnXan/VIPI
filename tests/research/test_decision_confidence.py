"""Test reference-based decision confidence analysis without model calls."""

import pytest

from research.ocr_eval.experiments.decision_confidence import (
    comparison_outcome,
    completeness_outcome,
    markdown,
    probability_map,
    summarize_group,
)


def test_probability_map_preserves_supported_provider_shapes_and_skips_invalid_values():
    assert probability_map(
        {
            "probabilities": [
                {"value": "complete", "probability": 0.75},
                {"value": "missing_text", "probability": 0.25},
                {"value": "uncertain", "probability": float("nan")},
            ]
        }
    ) == {"complete": 0.75, "missing_text": 0.25}
    assert probability_map({"probabilities": {"improved": 0.8, "worse": True}}) == {
        "improved": 0.8
    }
    assert probability_map({"probabilities": None}) == {}


def test_completeness_labels_keep_eighty_percent_and_full_reference_distinct():
    score = {"matched": 8, "total": 10, "valid": False}
    outcome = completeness_outcome("complete", score)
    assert outcome == {
        "at_least_80_percent": True,
        "full_reference_pass": False,
        "choice_matches_full_reference": False,
        "complete_below_80_percent": False,
    }

    low = completeness_outcome("complete", {"matched": 7, "total": 10, "valid": False})
    assert low["complete_below_80_percent"] is True
    assert (
        completeness_outcome("uncertain", score)["choice_matches_full_reference"]
        is None
    )


def test_confidence_summary_scores_calibration_separately_for_each_split():
    rows = [
        {
            "question": "completeness",
            "choice": "complete",
            "confidence": 0.8,
            "probabilities": {"complete": 0.8},
            "outcome": {
                "at_least_80_percent": True,
                "full_reference_pass": True,
                "choice_matches_full_reference": True,
                "complete_below_80_percent": False,
            },
        },
        {
            "question": "completeness",
            "choice": "missing_text",
            "confidence": 0.7,
            "probabilities": {"complete": 0.3},
            "outcome": {
                "at_least_80_percent": False,
                "full_reference_pass": False,
                "choice_matches_full_reference": True,
                "complete_below_80_percent": False,
            },
        },
    ]
    summary = summarize_group(rows)
    validation = summary["reference_validation"]
    assert validation["decided_choice_accuracy_vs_full_reference"] == 1
    assert validation["brier_p_complete_vs_full_reference"] == pytest.approx(0.065)
    assert validation["brier_p_complete_vs_at_least_80_percent"] == pytest.approx(0.065)
    assert validation["p_complete_vs_full_reference_bins"] == [
        {"range": "0.3-0.4", "count": 1, "observed_rate": 0},
        {"range": "0.8-0.9", "count": 1, "observed_rate": 1},
    ]


def test_comparison_label_uses_reference_matched_words():
    result = comparison_outcome(
        {"incumbent": "0001", "candidate": "0002", "comparison": "improved"},
        {
            "0001": {"matched": 6},
            "0002": {"matched": 8},
        },
    )
    assert result == {
        "expected_choice": "improved",
        "choice_correct": True,
        "candidate_better": True,
    }


def test_markdown_displays_provider_probabilities_and_both_completeness_targets():
    data = {
        "selected_images": 1,
        "unique_image_hashes": 1,
        "selection_filter": {"description": "fixture", "keys_sha256": "abc"},
        "method": {
            "limitations": "No threshold was fitted.",
            "comparison": "Word counts only.",
            "probabilities": "Native values only.",
        },
        "configurations": {
            "cloud-default": {
                "confidence_groups": [
                    {
                        "provider": "openai-decisions",
                        "model": "gpt-6-luna",
                        "question": "completeness",
                        "split": "evaluation",
                        "answers": 1,
                        "choices": {"complete": 1},
                        "confidence": {"mean": 0.9, "available": 1},
                        "option_probabilities": {
                            "complete": {"mean": 0.9, "available": 1}
                        },
                        "reference_validation": {
                            "decided_choice_accuracy_vs_full_reference": 1.0,
                            "decided_choice_count": 1,
                            "brier_p_complete_vs_full_reference": 0.01,
                            "brier_p_complete_vs_at_least_80_percent": 0.02,
                            "complete_below_80_percent_count": 0,
                        },
                    }
                ],
                "image_counts": {"evaluation/completed": 1},
                "no_decision_images_by_split": {},
            }
        },
    }

    rendered = markdown(data)

    assert "Mean option probabilities" in rendered
    assert "complete=0.900 (n=1)" in rendered
    assert "vs ≥80% 0.020" in rendered
