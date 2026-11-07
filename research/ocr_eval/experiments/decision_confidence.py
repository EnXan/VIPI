"""Validate decision confidence against retained OCR reference scores."""

import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path
from statistics import mean, median

from research.ocr_eval.benchmark import ROOT, catalogs, digest
from research.ocr_eval.benchmark_report import score_result, summarize


def probability_map(answer):
    """Return only provider-reported finite probabilities in the [0, 1] range."""
    values = answer.get("probabilities")
    if isinstance(values, dict):
        pairs = values.items()
    elif isinstance(values, list):
        pairs = (
            (item.get("value"), item.get("probability"))
            for item in values
            if isinstance(item, dict)
        )
    else:
        return {}
    return {
        label: float(value)
        for label, value in pairs
        if isinstance(label, str)
        and isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and 0 <= value <= 1
    }


def score_attempt(reference, attempt):
    """Score one retained OCR attempt with the benchmark's existing policy."""
    return score_result(
        reference,
        {
            "text": attempt.get("grouped_text") or attempt.get("text", ""),
            "regions": attempt.get("regions", []),
            "variants": [attempt],
        },
    )


def brier_score(pairs):
    if not pairs:
        return None
    return mean((probability - outcome) ** 2 for probability, outcome in pairs)


def reliability_bins(pairs):
    """Group reported probabilities into fixed-width descriptive bins."""
    buckets = [[] for _ in range(10)]
    for probability, outcome in pairs:
        buckets[min(9, int(probability * 10))].append(outcome)
    return [
        {
            "range": f"{index / 10:.1f}-{(index + 1) / 10:.1f}",
            "count": len(outcomes),
            "observed_rate": mean(outcomes) if outcomes else None,
        }
        for index, outcomes in enumerate(buckets)
        if outcomes
    ]


def percentage(value):
    return "—" if value is None else f"{value:.2%}"


def completeness_outcome(choice, score):
    """Relate a completeness choice to word coverage and the full-reference pass."""
    if score is None or not score["total"]:
        return None
    choice_matches_full_reference = None
    if choice in {"complete", "missing_text"}:
        choice_matches_full_reference = (choice == "complete") == score["valid"]
    return {
        "at_least_80_percent": score["matched"] * 5 >= score["total"] * 4,
        "full_reference_pass": score["valid"],
        "choice_matches_full_reference": choice_matches_full_reference,
        "complete_below_80_percent": choice == "complete"
        and score["matched"] * 5 < score["total"] * 4,
    }


def comparison_outcome(record, scores):
    """Check a comparison choice against tolerant matched-word counts."""
    incumbent = scores.get(record.get("incumbent"))
    candidate = scores.get(record.get("candidate"))
    if incumbent is None or candidate is None:
        return None
    if candidate["matched"] > incumbent["matched"]:
        expected = "improved"
    elif candidate["matched"] < incumbent["matched"]:
        expected = "worse"
    else:
        expected = "equivalent"
    return {
        "expected_choice": expected,
        "choice_correct": record.get("comparison") == expected,
        "candidate_better": expected == "improved",
    }


def collect_observations(directory, configuration, manifest, catalog_by_suite):
    source = Path(directory) / configuration
    session_path = source / "session.json"
    session = json.loads(session_path.read_text()) if session_path.exists() else {}
    split_by_hash = (manifest.get("selection_filter") or {}).get("confidence_split", {})
    observations = []
    image_counts = Counter()
    no_decision_counts = Counter()
    run_rows = {}

    for selected in manifest["selection"]:
        split = split_by_hash.get(selected["image_sha256"], "unassigned")
        image_counts[(split, "planned")] += 1
        row_path = source / "rows" / f"{selected['key'].replace(':', '-')}.json"
        if not row_path.exists():
            image_counts[(split, "unattempted")] += 1
            continue
        row = json.loads(row_path.read_text())
        image_counts[(split, row.get("status", "unknown"))] += 1
        if row.get("status") != "completed" or not row.get("artifacts"):
            continue

        result_path = Path(row["artifacts"]) / "result.json"
        if not result_path.exists():
            continue
        result = json.loads(result_path.read_text())
        decision_selection = result.get("selection") or {}
        variants = result.get("variants") or []
        reference = catalog_by_suite[selected["suite"]].reference(selected["id"])
        scores = {
            variant.get("id"): score_attempt(reference, variant) for variant in variants
        }
        initial_score = scores.get("0001")
        decision_rows = decision_selection.get("decisions") or []
        if not decision_rows:
            no_decision_counts[split] += 1
        for decision in decision_rows:
            response = decision.get("response") or {}
            response_model = response.get("model") or decision_selection.get("model")
            answers = response.get("answers") or {}
            for question, answer in answers.items():
                if not isinstance(answer, dict):
                    continue
                probabilities = probability_map(answer)
                outcome = None
                if question == "completeness":
                    outcome = completeness_outcome(answer.get("choice"), initial_score)
                elif question == "comparison":
                    outcome = comparison_outcome(decision, scores)
                observations.append(
                    {
                        "key": selected["key"],
                        "image_sha256": selected["image_sha256"],
                        "split": split,
                        "provider": decision_selection.get("provider")
                        or session.get("decision_provider")
                        or session.get("provider"),
                        "model": response_model
                        or session.get("decision_model")
                        or session.get("model"),
                        "question": question,
                        "choice": answer.get("choice"),
                        "confidence": answer.get("confidence"),
                        "probabilities": probabilities,
                        "outcome": outcome,
                    }
                )
        run_rows[selected["key"]] = initial_score
    return observations, image_counts, no_decision_counts, run_rows, session


def summarize_group(rows):
    confidences = [
        row["confidence"]
        for row in rows
        if isinstance(row["confidence"], (int, float))
        and not isinstance(row["confidence"], bool)
        and math.isfinite(row["confidence"])
        and 0 <= row["confidence"] <= 1
    ]
    options = defaultdict(list)
    choice_counts = Counter(row["choice"] for row in rows)
    for row in rows:
        for label, probability in row["probabilities"].items():
            options[label].append(probability)

    summary = {
        "answers": len(rows),
        "choices": dict(sorted(choice_counts.items())),
        "confidence": {
            "available": len(confidences),
            "mean": mean(confidences) if confidences else None,
            "median": median(confidences) if confidences else None,
        },
        "option_probabilities": {
            label: {"available": len(values), "mean": mean(values)}
            for label, values in sorted(options.items())
        },
    }

    if rows and rows[0]["question"] == "completeness":
        full_reference = []
        at_least_80 = []
        complete_below_80 = 0
        evaluable = []
        for row in rows:
            outcome = row["outcome"]
            if outcome is None:
                continue
            target_full = outcome["full_reference_pass"]
            target_80 = outcome["at_least_80_percent"]
            p_complete = row["probabilities"].get("complete")
            if p_complete is not None:
                full_reference.append((p_complete, target_full))
                at_least_80.append((p_complete, target_80))
            if outcome["choice_matches_full_reference"] is not None:
                evaluable.append(outcome["choice_matches_full_reference"])
            complete_below_80 += outcome["complete_below_80_percent"]
        summary["reference_validation"] = {
            "scored_answers": sum(row["outcome"] is not None for row in rows),
            "decided_choice_accuracy_vs_full_reference": mean(evaluable)
            if evaluable
            else None,
            "decided_choice_count": len(evaluable),
            "complete_below_80_percent_count": complete_below_80,
            "probability_scored_answers": len(full_reference),
            "brier_p_complete_vs_full_reference": brier_score(full_reference),
            "brier_p_complete_vs_at_least_80_percent": brier_score(at_least_80),
            "p_complete_vs_full_reference_bins": reliability_bins(full_reference),
        }
    elif rows and rows[0]["question"] == "comparison":
        evaluable = [
            row["outcome"]["choice_correct"]
            for row in rows
            if row["outcome"] is not None
        ]
        improved = [
            (row["probabilities"]["improved"], row["outcome"]["candidate_better"])
            for row in rows
            if row["outcome"] is not None and "improved" in row["probabilities"]
        ]
        summary["reference_validation"] = {
            "scored_comparisons": len(evaluable),
            "choice_accuracy_vs_tolerant_word_gain": mean(evaluable)
            if evaluable
            else None,
            "probability_scored_comparisons": len(improved),
            "brier_p_improved_vs_tolerant_word_gain": brier_score(improved),
            "p_improved_vs_tolerant_word_gain_bins": reliability_bins(improved),
        }
    return summary


def historical_baseline(path, keys, expected_sha256):
    """Summarize the frozen cohort from the original full evaluation."""
    path = Path(path)
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected_sha256:
        raise ValueError("Baseline report does not match the frozen source hash.")
    data = json.loads(path.read_text())
    output = {}
    for configuration, values in data["configurations"].items():
        rows_by_key = {row["key"]: row for row in values["rows"]}
        if not set(keys) <= set(rows_by_key):
            raise ValueError(f"Baseline is missing selected rows: {configuration}.")
        selected_rows = [rows_by_key[key] for key in keys]
        categories = defaultdict(list)
        for row in selected_rows:
            categories[row["category"]].append(row)
        output[configuration] = {
            "summary": summarize(selected_rows),
            "categories": {
                category: summarize(rows)
                for category, rows in sorted(categories.items())
            },
        }
    return output


def report(directory, baseline_report=None):
    """Summarize provider confidence and reference-based outcomes by split."""
    directory = Path(directory)
    manifest = json.loads((directory / "manifest.json").read_text())
    if not manifest.get("selection_filter", {}).get("confidence_split"):
        raise ValueError("Benchmark manifest has no frozen confidence split.")
    loaded_catalogs = catalogs()
    configurations = {}
    for configuration in manifest["configurations"]:
        (
            observations,
            image_counts,
            no_decision_counts,
            run_rows,
            session,
        ) = collect_observations(directory, configuration, manifest, loaded_catalogs)
        grouped = defaultdict(list)
        for row in observations:
            grouped[
                (row["provider"], row["model"], row["question"], row["split"])
            ].append(row)
        configurations[configuration] = {
            "session": session,
            "image_counts": {
                f"{split}/{status}": count
                for (split, status), count in sorted(image_counts.items())
            },
            "reference_scored_images": sum(
                score is not None for score in run_rows.values()
            ),
            "no_decision_images_by_split": dict(sorted(no_decision_counts.items())),
            "confidence_groups": [
                {
                    "provider": provider,
                    "model": model,
                    "question": question,
                    "split": split,
                    **summarize_group(rows),
                }
                for (provider, model, question, split), rows in sorted(
                    grouped.items(), key=lambda item: tuple(str(v) for v in item[0])
                )
            ],
        }
    result = {
        "schema_version": 1,
        "selection_filter": manifest["selection_filter"],
        "selected_images": len(manifest["selection"]),
        "unique_image_hashes": len(
            {row["image_sha256"] for row in manifest["selection"]}
        ),
        "categories": dict(
            sorted(Counter(row["category"] for row in manifest["selection"]).items())
        ),
        "method": {
            "labels": "Evaluation-v4 OCR reference scores computed offline after inference.",
            "completeness": "Initial OCR attempt is scored against both >=80% tolerant word coverage and the full-reference pass.",
            "comparison": "Candidate and incumbent are compared by tolerant matched-word counts; this does not score visual fidelity or geometry.",
            "probabilities": "Only native provider-reported confidence and per-option probabilities are summarized; absent values stay absent.",
            "limitations": "A held-out split within a difficulty-selected development subset is not an independent benchmark. No confidence threshold or production policy is fitted or changed.",
        },
        "postprocessing_sources": {
            filename: digest(ROOT / filename)
            for filename in (
                "research/ocr_eval/experiments/decision_confidence.py",
                "research/ocr_eval/benchmark_report.py",
                "research/ocr_eval/evaluation/metrics.py",
            )
        },
        "configurations": configurations,
    }
    if baseline_report is not None:
        result["historical_baseline"] = {
            "sha256": manifest["selection_filter"]["source_report_sha256"],
            "configurations": historical_baseline(
                baseline_report,
                [row["key"] for row in manifest["selection"]],
                manifest["selection_filter"]["source_report_sha256"],
            ),
        }
    return result


def markdown(data):
    """Render confidence summaries without hiding missing provider fields."""
    lines = [
        "# Decision confidence validation",
        "",
        f"Selected catalog entries: {data['selected_images']} ({data['unique_image_hashes']} unique image hashes).",
        f"Selection: {data['selection_filter']['description']}",
        f"Selection keys SHA-256: `{data['selection_filter']['keys_sha256']}`.",
        "",
        "Only native provider fields are summarized. Reference scores are computed offline after inference. No threshold or production policy is fitted.",
        "",
    ]
    if "historical_baseline" in data:
        lines.extend(
            [
                "## Previous full-evaluation results on the same selected entries",
                "",
                "| Configuration | Scored / failed | Tolerant coverage | Exact coverage | Images ≥80% / 100% | Full-reference pass | Mean seconds/image | Recorded API estimate |",
                "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for configuration, values in data["historical_baseline"][
            "configurations"
        ].items():
            summary = values["summary"]
            rates = summary["image_rates"]
            cost = summary["cost"]
            if cost["estimated_usd"] is None:
                estimate = (
                    f"unknown (${cost['recorded_estimate_subtotal']:.6f} recorded)"
                )
            else:
                estimate = f"${cost['estimated_usd']:.6f}"
            mean_seconds = summary["time"]["mean_image_seconds"]
            time_text = "—" if mean_seconds is None else f"{mean_seconds:.2f}"
            lines.append(
                f"| {configuration} | {summary['scored']} / {summary['failed']} | {percentage(summary['word_weighted_coverage'])} | {percentage(summary['word_weighted_exact_coverage'])} | {percentage(rates['at_least_80'])} / {percentage(rates['coverage_100'])} | {percentage(rates['reference_pass'])} | {time_text} | {estimate} |"
            )
        lines.extend(
            [
                "",
                "The full-reference evaluation code is unchanged; the previous full run used an earlier recovery implementation. This is a cohort comparison, not a controlled attribution of any difference to one code change.",
                "",
            ]
        )
    for configuration, values in data["configurations"].items():
        lines.extend(
            [
                f"## {configuration}",
                "",
                "| Provider / model | Question | Split | Answers | Choices | Mean selected-answer confidence | Mean option probabilities | Reference validation |",
                "| --- | --- | --- | ---: | --- | ---: | --- | --- |",
            ]
        )
        for group in values["confidence_groups"]:
            confidence = group["confidence"]["mean"]
            confidence_text = (
                "—"
                if confidence is None
                else f"{confidence:.3f} (n={group['confidence']['available']})"
            )
            probability_text = (
                ", ".join(
                    f"{label}={values['mean']:.3f} (n={values['available']})"
                    for label, values in group["option_probabilities"].items()
                )
                or "—"
            )
            validation = group.get("reference_validation", {})
            if group["question"] == "completeness":
                accuracy = validation.get("decided_choice_accuracy_vs_full_reference")
                brier = validation.get("brier_p_complete_vs_full_reference")
                validation_text = (
                    f"full-reference choice accuracy {accuracy:.3f} (n={validation['decided_choice_count']})"
                    if accuracy is not None
                    else "no scored choices"
                )
                if brier is not None:
                    validation_text += f"; Brier p(complete) {brier:.3f}"
                brier_80 = validation.get("brier_p_complete_vs_at_least_80_percent")
                if brier_80 is not None:
                    validation_text += f"; vs ≥80% {brier_80:.3f}"
                validation_text += (
                    "; complete below 80% "
                    f"{validation.get('complete_below_80_percent_count', 0)}"
                )
            elif group["question"] == "comparison":
                accuracy = validation.get("choice_accuracy_vs_tolerant_word_gain")
                brier = validation.get("brier_p_improved_vs_tolerant_word_gain")
                validation_text = (
                    f"word-gain choice accuracy {accuracy:.3f} (n={validation['scored_comparisons']})"
                    if accuracy is not None
                    else "no scored comparisons"
                )
                if brier is not None:
                    validation_text += f"; Brier p(improved) {brier:.3f}"
            else:
                validation_text = "descriptive only; no reference label"
            lines.append(
                f"| {group['provider'] or 'unknown'} / {group['model'] or 'unknown'} | {group['question']} | {group['split']} | {group['answers']} | {group['choices']} | {confidence_text} | {probability_text} | {validation_text} |"
            )
        lines.extend(["", "Image rows by split/status:", ""])
        lines.extend(
            f"- `{name}`: {count}" for name, count in values["image_counts"].items()
        )
        lines.extend(["", "Completed images without decision answers:"])
        no_decisions = values["no_decision_images_by_split"]
        if no_decisions:
            lines.extend(
                f"- `{split}`: {count}" for split, count in no_decisions.items()
            )
        else:
            lines.append("- None")
        lines.append("")
    lines.extend(
        [
            "## Limits",
            "",
            data["method"]["limitations"],
            "",
            data["method"]["comparison"],
            "",
            data["method"]["probabilities"],
            "",
        ]
    )
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--baseline-report", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    data = report(args.directory, args.baseline_report)
    output = args.output or args.directory / "decision-confidence.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(data, indent=2) + "\n")
    output.with_suffix(".md").write_text(markdown(data))


if __name__ == "__main__":
    main()
