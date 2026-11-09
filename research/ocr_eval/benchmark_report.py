"""Score retained OCR benchmark outputs without running models or changing selection."""

import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path
from statistics import mean, median
import time

from vipi.ocr.costs import cost_for_result, decisions_estimated_usd, DECISIONS_PRICING
from .benchmark import catalog, digest, selection, utc_now
from .evaluation.metrics import compare_words, final_observations


def score_result(reference, result):
    """Use the existing evaluation-v4 final-output comparison, including geometry."""
    if (
        not reference["reading_order_known"]
        and not result["regions"]
        and result["text"].strip()
    ):
        return None
    regions = (
        result["regions"]
        if reference["reading_order_known"]
        else final_observations(result["regions"], result["variants"])
    )
    final, _, _ = compare_words(reference, result["text"], regions)
    return {
        "matched": final["matched"],
        "total": final["total"],
        "coverage": final["coverage"],
        "valid": final["valid"],
        "group_conflicts": len(final.get("group_conflicts", [])),
        "exact_matched": final["exact"]["matched"],
        "exact_coverage": final["exact"]["coverage"],
        "exact_valid": final["exact"]["valid"],
    }


def summarize(rows):
    """Keep image success denominators fixed; distinguish macro and word-weighted coverage."""
    scored = [r for r in rows if r.get("score") and r["score"]["total"] > 0]
    attempted = [r for r in rows if r["status"] != "unattempted"]
    scores = [r["score"] for r in scored]
    times = [
        r["elapsed_seconds"] for r in attempted if r.get("elapsed_seconds") is not None
    ]
    costs = [
        r["cost_estimated_usd"]
        for r in attempted
        if r.get("cost_estimated_usd") is not None
    ]
    recorded_subtotal = sum(
        row.get("cost_recorded_subtotal_usd", row.get("cost_estimated_usd") or 0)
        for row in attempted
    )
    total_words = sum(s["total"] for s in scores)
    matched = sum(s["matched"] for s in scores)
    exact_matched = sum(s["exact_matched"] for s in scores)
    planned_words = sum(r["reference_words"] for r in rows)
    counts = {
        "at_least_80": sum(s["matched"] * 5 >= s["total"] * 4 for s in scores),
        "coverage_100": sum(s["matched"] == s["total"] for s in scores),
        "reference_pass": sum(s["valid"] is True for s in scores),
        "exact_100": sum(s["exact_matched"] == s["total"] for s in scores),
        "exact_reference_pass": sum(s["exact_valid"] is True for s in scores),
    }
    return {
        "images": len(rows),
        "attempted": len(attempted),
        "completed": sum(r["status"] == "completed" for r in rows),
        "failed": sum(r["status"] == "failed" for r in rows),
        "failure_counts": dict(
            Counter(
                r.get("error", "Unknown failure")
                for r in rows
                if r["status"] == "failed"
            )
        ),
        "unattempted": len(rows) - len(attempted),
        "scored": len(scored),
        "unscored_completed": sum(
            r["status"] == "completed" and not r.get("score") for r in rows
        ),
        "zero_word_references": sum(r["reference_words"] == 0 for r in rows),
        "group_conflict_images": sum(s["group_conflicts"] > 0 for s in scores),
        "counts": counts,
        "image_rates": {k: v / len(rows) if rows else None for k, v in counts.items()},
        "words": {
            "matched": matched,
            "exact_matched": exact_matched,
            "scored_total": total_words,
            "planned_total": planned_words,
        },
        "word_weighted_coverage": matched / total_words if total_words else None,
        "word_weighted_exact_coverage": exact_matched / total_words
        if total_words
        else None,
        "mean_image_coverage": mean(s["coverage"] for s in scores) if scores else None,
        "mean_image_exact_coverage": mean(s["exact_coverage"] for s in scores)
        if scores
        else None,
        "all_planned_word_coverage_lower_bound": matched / planned_words
        if planned_words
        else None,
        "all_planned_exact_word_coverage_lower_bound": exact_matched / planned_words
        if planned_words
        else None,
        "all_planned_mean_coverage_lower_bound": sum(s["coverage"] for s in scores)
        / len(rows)
        if rows
        else None,
        "time": {
            "measured_images": len(times),
            "unknown_images": len(attempted) - len(times),
            "image_seconds_total": sum(times),
            "mean_image_seconds": mean(times) if times else None,
            "median_image_seconds": median(times) if times else None,
            "p95_image_seconds": sorted(times)[math.ceil(0.95 * len(times)) - 1]
            if times
            else None,
        },
        "cost": {
            "currency": "USD",
            "known_images": len(costs),
            "unknown_images": len(attempted) - len(costs),
            "recorded_estimate_subtotal": recorded_subtotal,
            "recorded_estimate_per_attempt": recorded_subtotal / len(attempted)
            if attempted
            else None,
            "estimated_usd": sum(costs)
            if len(costs) == len(attempted) and attempted
            else None,
            "mean_estimated_usd_per_attempt": sum(costs) / len(attempted)
            if len(costs) == len(attempted) and attempted
            else None,
            "decision_http_attempts": sum(
                r.get("decision_http_attempts", 0) for r in rows
            ),
            "decision_api_calls": sum(r.get("decision_api_calls", 0) for r in rows),
            "ocr_api_calls": sum(r.get("ocr_api_calls", 0) for r in rows),
            "retry_uncertain_images": sum(
                r.get("retry_cost_uncertain", False) for r in rows
            ),
            "unreported_requests": sum(r.get("unreported_requests", 0) for r in rows),
        },
    }


def retained_usage(directory, model):
    """Price retained usage without assigning a fee to missing responses."""
    directory = Path(directory)
    steps_path = directory / "steps.jsonl"
    steps = (
        [json.loads(line) for line in steps_path.read_text().splitlines()]
        if steps_path.exists()
        else []
    )
    ocr_cost = (
        cost_for_result({"model": model, "variants": steps}) if steps and model else {}
    )
    subtotal = ocr_cost.get("estimated_usd") or 0.0
    responses = list((directory / "decisions").rglob("response.json"))
    requests = list((directory / "decisions").rglob("request.json"))
    attempts, unreported = (
        0,
        sum(not (p.parent / "response.json").exists() for p in requests),
    )
    for path in responses:
        record = json.loads(path.read_text())
        estimate = decisions_estimated_usd(record.get("response", {}).get("usage", {}))
        if isinstance(estimate, (int, float)):
            subtotal += estimate
        else:
            unreported += 1
        attempts += record.get("attempts", 1)
    events_path = directory / "events.jsonl"
    events = (
        [json.loads(line) for line in events_path.read_text().splitlines()]
        if events_path.exists()
        else []
    )
    ocr_calls = sum(event["type"] == "ocr_started" for event in events)
    unreported += max(0, ocr_calls - len(steps))
    paths = [*responses, *requests, *([steps_path] if steps_path.exists() else [])]
    return {
        "cost_recorded_subtotal_usd": subtotal,
        "decision_api_calls": len(requests),
        "decision_http_attempts": attempts,
        "ocr_api_calls": ocr_calls,
        "unreported_requests": unreported,
        "retry_cost_uncertain": attempts > len(responses),
        "partial_usage_hashes": {
            p.relative_to(directory).as_posix(): digest(p) for p in sorted(paths)
        },
    }


def grouped(rows):
    """Content rows partition the dataset; other facets overlap and must not be summed."""
    groups = defaultdict(list)
    for row in rows:
        groups[("content", row["content"])].append(row)
        groups[("label", row["label"])].append(row)
        groups[("scope", row["scope"])].append(row)
        for facet in ("techniques", "obfuscation"):
            for value in row[facet]:
                groups[(facet, value)].append(row)
    return [
        {"facet": facet, "label": label, **summarize(items)}
        for (facet, label), items in sorted(groups.items())
    ]


def report(directory, cloud_directory=None):
    """Pair measured configurations only when inputs and evaluation rules agree."""
    directory = Path(directory)
    manifest = json.loads((directory / "manifest.json").read_text())
    from .benchmark import ROOT

    for filename, expected in manifest["provenance"]["source_hashes"].items():
        if (
            filename.startswith("research/ocr_eval/evaluation/")
            and digest(ROOT / filename) != expected
        ):
            raise ValueError(f"Evaluation code changed since inference: {filename}")
    complete_selection = selection()
    complete_by_key = {row["key"]: row for row in complete_selection}
    selected_keys = [row["key"] for row in manifest["selection"]]
    selected_key_set = set(selected_keys)
    if len(selected_keys) != len(set(selected_keys)) or any(
        complete_by_key.get(row["key"]) != row for row in manifest["selection"]
    ):
        raise ValueError(
            "Catalogs, references or images differ from the frozen selection."
        )
    expected_order = [
        row["key"] for row in complete_selection if row["key"] in selected_key_set
    ]
    if selected_keys != expected_order:
        raise ValueError("Frozen selection is not in active catalog order.")
    selection_filter = manifest.get("selection_filter")
    if selection_filter is None and manifest["selection"] != complete_selection:
        raise ValueError("A partial selection must include its selection basis.")
    if selection_filter is not None:
        keys_sha256 = hashlib.sha256(
            json.dumps(selected_keys, separators=(",", ":")).encode()
        ).hexdigest()
        if selection_filter.get("keys_sha256") != keys_sha256:
            raise ValueError("Selection basis does not match the frozen keys.")
        split = selection_filter.get("confidence_split")
        if split is not None:
            if not isinstance(split, dict):
                raise ValueError(
                    "Confidence split must map image hashes to split names."
                )
            split_values = set(split.values())
            if (
                set(split) != {row["image_sha256"] for row in manifest["selection"]}
                or not split_values <= {"calibration", "evaluation"}
                or split_values != {"calibration", "evaluation"}
            ):
                raise ValueError(
                    "Confidence split does not match selected image hashes."
                )
    dataset = catalog()
    configurations = {}
    sources = {}
    started = time.perf_counter()
    for configuration in manifest["configurations"]:
        source_directory = (
            Path(cloud_directory)
            if configuration == "cloud-default" and cloud_directory is not None
            else directory
        )
        source_path = source_directory / "manifest.json"
        source_manifest = json.loads(source_path.read_text())
        for field in (
            "selection",
            "selection_filter",
            "evaluation_policy",
            "configurations",
        ):
            if source_manifest.get(field) != manifest.get(field):
                raise ValueError(f"Configuration manifests disagree on {field}.")
        for filename, expected in source_manifest["provenance"][
            "source_hashes"
        ].items():
            if (
                filename.startswith("research/ocr_eval/evaluation/")
                and digest(ROOT / filename) != expected
            ):
                raise ValueError(f"Evaluation code changed since inference: {filename}")
        sources[configuration] = {
            "manifest_sha256": digest(source_path),
            "provenance": source_manifest["provenance"],
            "protocol": source_manifest["protocol"],
        }
        session_path = source_directory / configuration / "session.json"
        session = (
            json.loads(session_path.read_text()) if session_path.exists() else None
        )
        rows = []
        for selected in manifest["selection"]:
            saved = (
                source_directory
                / configuration
                / "rows"
                / f"{selected['key'].replace(':', '-')}.json"
            )
            attempt = (
                json.loads(saved.read_text())
                if saved.exists()
                else {"status": "unattempted"}
            )
            row = {**selected, **attempt}
            row["score"] = None
            if row["status"] == "completed":
                result_path = Path(row["artifacts"]) / "result.json"
                if digest(result_path) != row["result_sha256"]:
                    raise ValueError(f"Saved output changed: {row['key']}")
                result = json.loads(result_path.read_text())
                reference = dataset.reference(row["id"])
                row["score"] = score_result(reference, result)
                if row["score"] is None:
                    row["unscored_reason"] = (
                        "Word locations required but missing from nonempty transcription."
                    )
                elif row["score"]["total"] == 0:
                    row["unscored_reason"] = "Reference has no scorable words."
                elif row["score"]["total"] != row["reference_words"]:
                    raise ValueError(f"Reference word count changed: {row['key']}")
            cost = row.get("cost", {})
            row["cost_estimated_usd"] = (
                0.0
                if configuration == "local-speed" and row["status"] != "unattempted"
                else cost.get("estimated_usd")
            )
            row["decision_http_attempts"] = cost.get("selection_http_attempts", 0)
            row["decision_api_calls"] = cost.get("selection_api_calls", 0)
            row["ocr_api_calls"] = cost.get("ocr_api_calls", 0)
            row["retry_cost_uncertain"] = (
                row["decision_http_attempts"] > row["decision_api_calls"]
            )
            row["cost_recorded_subtotal_usd"] = row["cost_estimated_usd"] or 0.0
            if configuration == "cloud-default" and row.get("artifacts"):
                row.update(
                    retained_usage(row["artifacts"], (session or {}).get("model"))
                )
                row["pipeline_estimated_usd"] = cost.get("estimated_usd")
                if row["status"] == "completed" and not row["unreported_requests"]:
                    row["cost_estimated_usd"] = row["cost_recorded_subtotal_usd"]
            # Raw paths and usage remain in the retained run, not in the shareable report.
            row["run_id"] = (
                Path(row.pop("artifacts")).name if row.get("artifacts") else None
            )
            row.pop("cost", None)
            rows.append(row)
        summary = summarize(rows)
        invocations_path = source_directory / configuration / "invocations.json"
        invocations = (
            json.loads(invocations_path.read_text())
            if invocations_path.exists()
            else []
        )
        summary["time"]["invocation_wall_seconds"] = sum(
            v["elapsed_seconds"] for v in invocations
        )
        summary["time"]["invocations"] = invocations
        configurations[configuration] = {
            "session": session,
            "summary": summary,
            "groups": grouped(rows),
            "rows": rows,
        }
    return {
        "schema_version": 1,
        "inference_complete": all(
            value["summary"]["unattempted"] == 0 for value in configurations.values()
        ),
        "scored_at": utc_now(),
        "scoring_seconds": time.perf_counter() - started,
        "selection": manifest["selection"],
        "selection_filter": selection_filter,
        "evaluation_policy": manifest["evaluation_policy"],
        "decision_pricing": DECISIONS_PRICING,
        "postprocessing_sources": {
            name: digest(ROOT / name)
            for name in (
                "research/ocr_eval/benchmark_report.py",
                "src/vipi/ocr/costs.py",
            )
        },
        "configuration_sources": sources,
        "configurations": configurations,
    }


def percent(value):
    return "—" if value is None else f"{value * 100:.2f}%"


def markdown(data):
    """Render the same aggregates used by the machine-readable report."""
    image_count = len(data["selection"])
    scope = (
        "pinned images"
        if data.get("selection_filter") is None
        else "selected difficult images"
    )
    lines = [
        f"# OCR benchmark: {image_count:,} {scope}",
        "",
        "Generated from retained product OCR outputs. See the benchmark protocol for scope, denominators and cost limitations.",
        "",
        "This selected development sample measures OCR recovery, not final injection detection. USD figures are estimates from retained provider usage, not invoices; host hardware cost and electricity are unmeasured.",
        "",
    ]
    if data.get("selection_filter"):
        lines += [
            f"Selection: {data['selection_filter']['description']}",
            f"Selection key SHA-256: `{data['selection_filter']['keys_sha256']}`.",
            "",
        ]
    if not data["inference_complete"]:
        lines += ["**Partial run: some planned images have not been attempted.**", ""]
    for configuration, values in data["configurations"].items():
        provenance = data["configuration_sources"][configuration]["provenance"]
        hardware = provenance.get("hardware", {})
        cpu = hardware.get("machdep.cpu.brand_string") or "CPU unavailable"
        physical = hardware.get("hw.physicalcpu") or "?"
        logical = hardware.get("hw.logicalcpu") or "?"
        memory = hardware.get("hw.memsize")
        memory_text = (
            f"{int(memory) / 1024**3:.1f} GiB"
            if memory is not None
            else "memory unavailable"
        )
        lines += [
            f"## {configuration}",
            "",
            f"Runner host (provider inference runs remotely): {provenance.get('platform', 'platform unavailable')}; {cpu}; {physical} physical / {logical} logical CPUs; {memory_text}.",
            "",
            "| Category/subset | N | Scored / failed | Word coverage | Exact word coverage | Mean image coverage | ≥80% images | 100% images | Full-reference pass | Image seconds total / mean | API estimate USD total / mean |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
        for label, summary in [
            ("All images", values["summary"]),
            *((g["facet"] + "/" + g["label"], g) for g in values["groups"]),
        ]:
            duration = summary["time"]
            cost = summary["cost"]
            amount = (
                f"${cost['estimated_usd']:.6f} / ${cost['mean_estimated_usd_per_attempt']:.8f}"
                if cost["estimated_usd"] is not None
                else (
                    f"unknown (${cost['recorded_estimate_subtotal']:.6f} recorded / "
                    f"${cost['recorded_estimate_per_attempt']:.8f} per image)"
                    if cost["recorded_estimate_per_attempt"] is not None
                    else "unknown"
                )
            )
            mean_time = duration["mean_image_seconds"]
            time_text = (
                f"{duration['image_seconds_total']:.2f} / {mean_time:.2f}"
                if mean_time is not None
                else "—"
            )
            rates = summary["image_rates"]
            lines.append(
                f"| {label} | {summary['images']} | {summary['scored']} / {summary['failed']} | {percent(summary['word_weighted_coverage'])} | {percent(summary['word_weighted_exact_coverage'])} | {percent(summary['mean_image_coverage'])} | {percent(rates['at_least_80'])} | {percent(rates['coverage_100'])} | {percent(rates['reference_pass'])} | {time_text} | {amount} |"
            )
        lines += [
            "",
            f"Content rows partition the {image_count:,} selected image entries. Label, scope, technique and obfuscation rows overlap; do not add them together. Coverage averages use scored images; image success rates use every planned image in the row, including failures and unscored outputs. Durations are measured OCR call durations, including lazy model loading, but excluding worker startup/teardown and offline scoring.",
            "",
        ]
        wall = values["summary"]["time"]["invocation_wall_seconds"]
        count = values["summary"]["images"]
        lines += [
            f"Recorded invocation wall time: {wall:.2f}s; {wall / count:.2f}s per planned image (includes process overhead).",
            "",
        ]
    return "\n".join(lines)


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path, help="Retained benchmark directory")
    parser.add_argument(
        "--cloud-directory",
        type=Path,
        help="Use a separate complete cloud trial with matching inputs and evaluation rules",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Write JSON here and a Markdown sibling",
    )
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    data = report(args.directory.resolve(), args.cloud_directory)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(data, separators=(",", ":"), allow_nan=False) + "\n",
        encoding="utf-8",
    )
    args.output.with_suffix(".md").write_text(markdown(data), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
