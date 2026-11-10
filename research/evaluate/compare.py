"""Compare a run with its baseline: aggregates, content types and cases.

Inputs are both run summaries plus their local ``report.json`` files. Without
the baseline's local report (for example a baseline saved on another machine)
only aggregates are compared. The comparison reports values, deltas and
per-case changes next to failures, time, cost and resources; it does not
accept or reject a change. Value versus complexity remains a reviewed judgment
recorded in the Markdown output.
"""

import json
from pathlib import Path
import subprocess

from research.ocr_eval import benchmark
from vipi.storage.files import write_json

from research.ocr_eval.benchmark_report import expected_verdict, verdict

from . import suite

COMPARISON_KIND = "vipi-evaluation-comparison"
AGGREGATES = (
    ("completed", ("completed",)),
    ("failed", ("failed",)),
    ("scored", ("scored",)),
    ("word coverage (tolerant)", ("word_weighted_coverage",)),
    ("word coverage (exact)", ("word_weighted_exact_coverage",)),
    ("mean image coverage", ("mean_image_coverage",)),
    ("images ≥80% covered", ("image_rates", "at_least_80")),
    ("images 100% covered", ("image_rates", "coverage_100")),
    ("full reference pass", ("image_rates", "reference_pass")),
    ("exact 100% images", ("image_rates", "exact_100")),
    ("attacks flagged (recall)", ("detection", "recall")),
    ("benign flagged (false-positive rate)", ("detection", "false_positive_rate")),
    ("detection accuracy", ("detection", "accuracy")),
    ("unclear verdicts", ("detection", "unclear")),
    ("scans without result", ("detection", "no_result")),
    ("mean seconds per image", ("time", "mean_image_seconds")),
    ("median seconds per image", ("time", "median_image_seconds")),
    ("p95 seconds per image", ("time", "p95_image_seconds")),
    ("estimated cost USD (all known)", ("cost", "estimated_usd")),
    ("recorded cost subtotal USD", ("cost", "recorded_estimate_subtotal")),
    ("requests without usage", ("cost", "unreported_requests")),
)
OPERATIONS = (
    ("run wall seconds", "wall_seconds"),
    ("CPU seconds (lower bound)", "cpu_seconds_lower_bound"),
    ("peak RSS bytes", "peak_rss_bytes"),
)
CASE_GROUPS = (
    "newly_failed",
    "recovered",
    "regressed",
    "improved",
    "detection_regressed",
    "detection_improved",
    "detection_changed",
)
RATE_FIELDS = (
    "coverage",
    "covered",
    "pass",
    "exact 100%",
    "rate",
    "accuracy",
    "recall",
)


def local_report(summary, root):
    """The configuration's scored rows, or None when the report is not local."""
    path = Path(root) / summary["local_artifacts"] / "report.json"
    if not path.is_file():
        return None
    if benchmark.digest(path) != summary["report_sha256"]:
        raise ValueError(f"{path} differs from its run summary.")
    report = json.loads(path.read_text(encoding="utf-8"))
    return report["configurations"][summary["manifest"]["configuration_name"]]


def lookup(values, fields):
    for field in fields:
        if not isinstance(values, dict):
            return None
        values = values.get(field)
    return values


def delta(baseline, candidate):
    if isinstance(baseline, bool) or isinstance(candidate, bool):
        return None
    if isinstance(baseline, (int, float)) and isinstance(candidate, (int, float)):
        return candidate - baseline
    return None


def aggregate_rows(baseline, candidate):
    rows = [
        {
            "metric": label,
            "baseline": lookup(baseline["metrics"], fields),
            "candidate": lookup(candidate["metrics"], fields),
        }
        for label, fields in AGGREGATES
    ] + [
        {
            "metric": label,
            "baseline": baseline["operations"].get(field),
            "candidate": candidate["operations"].get(field),
        }
        for label, field in OPERATIONS
    ]
    return [{**row, "delta": delta(row["baseline"], row["candidate"])} for row in rows]


def content_rows(baseline_groups, candidate_groups):
    def by_label(groups):
        return {
            group["label"]: group for group in groups if group["facet"] == "content"
        }

    first, second = by_label(baseline_groups), by_label(candidate_groups)
    rows = []
    for label in sorted(set(first) | set(second)):
        values = [
            lookup(group, ("word_weighted_coverage",))
            for group in (first.get(label), second.get(label))
        ]
        failures = [
            lookup(group, ("failed",))
            for group in (first.get(label), second.get(label))
        ]
        accuracy = [
            lookup(group, ("detection", "accuracy"))
            for group in (first.get(label), second.get(label))
        ]
        rows.append(
            {
                "content": label,
                "images": lookup(first.get(label) or second.get(label), ("images",)),
                "baseline_coverage": values[0],
                "candidate_coverage": values[1],
                "delta": delta(*values),
                "baseline_failed": failures[0],
                "candidate_failed": failures[1],
                "baseline_accuracy": accuracy[0],
                "candidate_accuracy": accuracy[1],
                "accuracy_delta": delta(*accuracy),
            }
        )
    return rows


def detection_change(key, before, after):
    """Classify a changed detection outcome; return None when it is unchanged."""
    expected = expected_verdict(before)
    first, second = verdict(before), verdict(after)
    if first == second:
        return None
    record = {
        "key": key,
        "expected": expected,
        "baseline_verdict": first,
        "candidate_verdict": second,
    }
    if first == expected:
        return "detection_regressed", record
    if second == expected:
        return "detection_improved", record
    return "detection_changed", record


def case_change(key, before, after):
    """Classify one OCR case; return None when nothing changed."""
    record = {
        "key": key,
        "baseline_status": before["status"],
        "candidate_status": after["status"],
        "baseline_coverage": lookup(before, ("score", "coverage")),
        "candidate_coverage": lookup(after, ("score", "coverage")),
        "baseline_pass": lookup(before, ("score", "valid")),
        "candidate_pass": lookup(after, ("score", "valid")),
    }
    if before["status"] == "completed" and after["status"] != "completed":
        return "newly_failed", {**record, "error": after.get("error")}
    if before["status"] != "completed" and after["status"] == "completed":
        return "recovered", record
    change = delta(record["baseline_coverage"], record["candidate_coverage"])
    if change is None:
        return None
    if change < 0 or (record["baseline_pass"] and not record["candidate_pass"]):
        return "regressed", {**record, "delta": change}
    if change > 0 or (record["candidate_pass"] and not record["baseline_pass"]):
        return "improved", {**record, "delta": change}
    return None


def case_changes(baseline_rows, candidate_rows):
    before = {row["key"]: row for row in baseline_rows}
    after = {row["key"]: row for row in candidate_rows}
    changes = {name: [] for name in CASE_GROUPS}
    # Unmatched runs may cover different entries; only shared entries compare.
    for key in sorted(set(before) & set(after)):
        for classify in (case_change, detection_change):
            classified = classify(key, before[key], after[key])
            if classified:
                changes[classified[0]].append(classified[1])
    for name in ("regressed", "improved"):
        changes[name].sort(key=lambda item: (abs(item["delta"]) * -1, item["key"]))
    return changes


def code_surface(baseline, candidate, root):
    """Summarize changed code between clean commits; otherwise ask for a manual note."""
    first = baseline["implementation"]
    second = candidate["implementation"]
    if first.get("dirty") or second.get("dirty"):
        return {
            "available": False,
            "reason": "A run used uncommitted changes; describe the code surface manually.",
        }
    if first["commit"] == second["commit"]:
        return {"available": True, "commits": [first["commit"]], "files": []}
    try:
        output = subprocess.run(
            ["git", "diff", "--numstat", first["commit"], second["commit"]],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as error:
        return {"available": False, "reason": f"git diff failed: {error}"}
    files = []
    for line in output.splitlines():
        added, removed, name = line.split("\t", 2)
        files.append(
            {
                "file": name,
                "added": None if added == "-" else int(added),
                "removed": None if removed == "-" else int(removed),
            }
        )
    return {
        "available": True,
        "commits": [first["commit"], second["commit"]],
        "files": files,
    }


def compare(baseline, candidate, root=benchmark.ROOT):
    """Compare two run summaries of the same configuration and split."""
    root = Path(root)
    differences = suite.differences(
        suite.comparable(baseline["manifest"], baseline.get("implementation"), root),
        suite.comparable(candidate["manifest"], candidate.get("implementation"), root),
    )
    first, second = local_report(baseline, root), local_report(candidate, root)
    changes = case_changes(first["rows"], second["rows"]) if first and second else None
    return {
        "kind": COMPARISON_KIND,
        "schema_version": 2,
        "configuration": candidate["manifest"]["configuration_name"],
        "split": candidate["manifest"]["split"],
        "baseline": {"run_id": baseline["run_id"]},
        "candidate": {"run_id": candidate["run_id"]},
        "matched": not differences,
        "differences": differences,
        "host_differs": baseline["host"] != candidate["host"],
        "aggregates": aggregate_rows(baseline, candidate),
        "contents": content_rows(first["groups"], second["groups"])
        if first and second
        else [],
        "case_counts": {name: len(items) for name, items in changes.items()}
        if changes
        else None,
        "cases": changes,
        "code_surface": code_surface(baseline, candidate, root),
    }


def number(value, label=""):
    if value is None:
        return "—"
    if isinstance(value, float) and any(word in label for word in RATE_FIELDS):
        return f"{value * 100:.2f}%"
    if isinstance(value, float):
        return f"{value:.4g}"
    return f"{value:,}"


def signed(value, label=""):
    if value is None:
        return "—"
    if isinstance(value, float) and any(word in label for word in RATE_FIELDS):
        return f"{value * 100:+.2f} pp"
    return f"{value:+.4g}" if isinstance(value, float) else f"{value:+,}"


def case_table(items):
    lines = ["| Entry | Baseline | This run | Change |", "| --- | --- | --- | --- |"]
    for item in items:
        before = (
            number(item["baseline_coverage"], "coverage")
            if item["baseline_status"] == "completed"
            else item["baseline_status"]
        )
        after = (
            number(item["candidate_coverage"], "coverage")
            if item["candidate_status"] == "completed"
            else item["candidate_status"]
        )
        change = signed(item.get("delta"), "coverage") if "delta" in item else "—"
        lines.append(f"| `{item['key']}` | {before} | {after} | {change} |")
    if not items:
        lines.append("| none | | | |")
    return lines


def verdict_table(items):
    lines = [
        "| Entry | Expected | Baseline | This run |",
        "| --- | --- | --- | --- |",
    ]
    lines += [
        f"| `{item['key']}` | {item['expected']} | {item['baseline_verdict']} | "
        f"{item['candidate_verdict']} |"
        for item in items
    ]
    if not items:
        lines.append("| none | | | |")
    return lines


CASE_SECTIONS = (
    ("newly_failed", "Scan newly failed", case_table),
    ("regressed", "OCR regressed", case_table),
    ("recovered", "Scan recovered", case_table),
    ("improved", "OCR improved", case_table),
    ("detection_regressed", "Detection now wrong", verdict_table),
    ("detection_improved", "Detection now right", verdict_table),
    ("detection_changed", "Detection changed, still wrong", verdict_table),
)


def markdown(data):
    lines = [
        f"# Comparison with the baseline: {data['configuration']} ({data['split']})",
        "",
        f"- Baseline: `{data['baseline']['run_id']}`",
        f"- This run: `{data['candidate']['run_id']}`",
        f"- Same inputs: {'yes' if data['matched'] else 'NO'}",
    ]
    if not data["matched"]:
        lines.append(f"- Differences: {', '.join(data['differences'])}")
        lines.append("- Not a direct comparison; save a new baseline first.")
    if data["host_differs"]:
        lines.append(
            "- Host or package versions differ; time and resources are not directly comparable."
        )
    lines += [
        "",
        "## Aggregates",
        "",
        "| Metric | Baseline | This run | Delta |",
        "| --- | --- | --- | --- |",
    ]
    for row in data["aggregates"]:
        label = row["metric"]
        lines.append(
            f"| {label} | {number(row['baseline'], label)} | "
            f"{number(row['candidate'], label)} | {signed(row['delta'], label)} |"
        )
    if data["cases"] is None:
        lines += [
            "",
            "The baseline's per-entry report is not on this machine; content rows "
            "and per-entry changes are unavailable. Run and save a baseline here.",
        ]
    else:
        lines += [
            "",
            "## Content types",
            "",
            "| Content | Images | OCR coverage (baseline → this run) | Delta | "
            "Detection accuracy (baseline → this run) | Delta | Failed scans |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
        for row in data["contents"]:
            lines.append(
                f"| {row['content']} | {number(row['images'])} | "
                f"{number(row['baseline_coverage'], 'coverage')} → "
                f"{number(row['candidate_coverage'], 'coverage')} | "
                f"{signed(row['delta'], 'coverage')} | "
                f"{number(row['baseline_accuracy'], 'accuracy')} → "
                f"{number(row['candidate_accuracy'], 'accuracy')} | "
                f"{signed(row['accuracy_delta'], 'accuracy')} | "
                f"{number(row['baseline_failed'])} → {number(row['candidate_failed'])} |"
            )
        counts = data["case_counts"]
        lines += [
            "",
            "## Entries",
            "",
            ", ".join(f"{title} {counts[name]}" for name, title, _ in CASE_SECTIONS)
            + ".",
        ]
        for name, title, table in CASE_SECTIONS:
            lines += ["", f"### {title}", "", *table(data["cases"][name])]
    surface = data["code_surface"]
    lines += ["", "## Value versus complexity", ""]
    if surface["available"]:
        added = sum(item["added"] or 0 for item in surface["files"])
        removed = sum(item["removed"] or 0 for item in surface["files"])
        lines.append(
            f"Changed between runs: {len(surface['files'])} files, +{added}/-{removed} lines."
        )
        lines += [f"- `{item['file']}`" for item in surface["files"]]
    else:
        lines.append(surface["reason"])
    lines += [
        "",
        "Reviewer notes (fill in): new modules, branches, dependencies and "
        "operational requirements; whether the measured quality and efficiency "
        "changes justify them.",
        "",
    ]
    return "\n".join(lines)


def write(data, directory):
    """Write ``comparison.json`` and ``comparison.md`` into a run directory."""
    directory = Path(directory)
    json_path = directory / "comparison.json"
    write_json(json_path, data)
    markdown_path = directory / "comparison.md"
    markdown_path.write_text(markdown(data), encoding="utf-8")
    return json_path, markdown_path
