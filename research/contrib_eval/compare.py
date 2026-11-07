"""Compare a candidate run with its baseline: aggregates, categories and cases.

Inputs are the committed run summaries plus the local ``report.json`` of both
runs (needed for per-case changes). The comparison reports values, deltas and
per-case regressions next to failures, time, cost and resources; it does not
rank or accept a contribution. Value versus complexity remains a reviewed
judgment recorded in the Markdown output.
"""

import json
from pathlib import Path
import subprocess

from research.ocr_eval import benchmark
from vipi.storage.files import write_json

from . import suite

COMPARISON_KIND = "vipi-contribution-comparison"
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
RATE_FIELDS = ("coverage", "covered", "pass", "exact 100%")


def find_summary(run_id, root):
    matches = sorted(Path(root).glob(f"research/*/reports/contrib/{run_id}.json"))
    if len(matches) != 1:
        raise ValueError(f"Run {run_id!r} not found in committed reports.")
    summary = json.loads(matches[0].read_text(encoding="utf-8"))
    if summary.get("kind") != suite.SUMMARY_KIND:
        raise ValueError(f"{matches[0]} is not a run summary.")
    return matches[0], summary


def local_report(summary, root):
    path = Path(root) / summary["local_artifacts"] / "report.json"
    if not path.is_file():
        raise ValueError(
            f"Per-case report for {summary['run_id']} is not available locally: {path}"
        )
    if benchmark.digest(path) != summary["report_sha256"]:
        raise ValueError(f"{path} differs from the committed summary.")
    report = json.loads(path.read_text(encoding="utf-8"))
    configuration = next(
        iter(summary["manifest"]["configuration"]["benchmark_configuration"])
    )
    return report["configurations"][configuration]


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


def category_rows(baseline_groups, candidate_groups):
    def by_label(groups):
        return {
            group["label"]: group for group in groups if group["facet"] == "category"
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
        rows.append(
            {
                "category": label,
                "images": lookup(first.get(label) or second.get(label), ("images",)),
                "baseline_coverage": values[0],
                "candidate_coverage": values[1],
                "delta": delta(*values),
                "baseline_failed": failures[0],
                "candidate_failed": failures[1],
            }
        )
    return rows


def case_change(key, before, after):
    """Classify one case; return None when nothing changed."""
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
    if set(before) != set(after):
        raise ValueError("Baseline and candidate cover different cases.")
    changes = {"newly_failed": [], "recovered": [], "regressed": [], "improved": []}
    for key in sorted(before):
        classified = case_change(key, before[key], after[key])
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


def compare(baseline_id, candidate_id, root=benchmark.ROOT):
    root = Path(root)
    baseline_path, baseline = find_summary(baseline_id, root)
    candidate_path, candidate = find_summary(candidate_id, root)
    if baseline["role"] != "baseline" or candidate["role"] != "candidate":
        raise ValueError("Compare a baseline run with a candidate run.")
    if candidate["comparison"]["baseline_run_id"] != baseline_id:
        raise ValueError(
            f"Candidate {candidate_id} was run against "
            f"{candidate['comparison']['baseline_run_id']}, not {baseline_id}."
        )
    differences = suite.differences(baseline["manifest"], candidate["manifest"])
    first, second = local_report(baseline, root), local_report(candidate, root)
    changes = case_changes(first["rows"], second["rows"])
    return {
        "kind": COMPARISON_KIND,
        "schema_version": 1,
        "path": baseline["manifest"]["path"],
        "split": baseline["manifest"]["split"],
        "baseline": {
            "run_id": baseline_id,
            "summary": baseline_path.relative_to(root).as_posix(),
        },
        "candidate": {
            "run_id": candidate_id,
            "summary": candidate_path.relative_to(root).as_posix(),
        },
        "matched": not differences,
        "differences": differences,
        "mismatch_reason": candidate["comparison"].get("mismatch_reason"),
        "host_differs": baseline["host"] != candidate["host"],
        "aggregates": aggregate_rows(baseline, candidate),
        "categories": category_rows(first["groups"], second["groups"]),
        "case_counts": {name: len(items) for name, items in changes.items()},
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


def case_table(items, limit_note):
    lines = ["| Case | Baseline | Candidate | Change |", "| --- | --- | --- | --- |"]
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
        lines.append(f"| none | | | {limit_note} |")
    return lines


def markdown(data):
    lines = [
        f"# Contribution comparison: {data['path']} ({data['split']})",
        "",
        f"- Baseline: `{data['baseline']['run_id']}`",
        f"- Candidate: `{data['candidate']['run_id']}`",
        f"- Matched inputs: {'yes' if data['matched'] else 'NO'}",
    ]
    if not data["matched"]:
        lines.append(f"- Differences: {', '.join(data['differences'])}")
        lines.append(f"- Recorded reason: {data['mismatch_reason'] or '—'}")
        lines.append("- Not a direct performance comparison.")
    if data["host_differs"]:
        lines.append(
            "- Host or package versions differ; time and resources are not directly comparable."
        )
    lines += [
        "",
        "## Aggregates",
        "",
        "| Metric | Baseline | Candidate | Delta |",
        "| --- | --- | --- | --- |",
    ]
    for row in data["aggregates"]:
        label = row["metric"]
        lines.append(
            f"| {label} | {number(row['baseline'], label)} | "
            f"{number(row['candidate'], label)} | {signed(row['delta'], label)} |"
        )
    lines += [
        "",
        "## Categories (tolerant word coverage)",
        "",
        "| Category | Images | Baseline | Candidate | Delta | Failed (b → c) |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in data["categories"]:
        lines.append(
            f"| {row['category']} | {number(row['images'])} | "
            f"{number(row['baseline_coverage'], 'coverage')} | "
            f"{number(row['candidate_coverage'], 'coverage')} | "
            f"{signed(row['delta'], 'coverage')} | "
            f"{number(row['baseline_failed'])} → {number(row['candidate_failed'])} |"
        )
    counts = data["case_counts"]
    lines += [
        "",
        "## Cases",
        "",
        f"Newly failed {counts['newly_failed']}, recovered {counts['recovered']}, "
        f"regressed {counts['regressed']}, improved {counts['improved']}.",
    ]
    for name, title in (
        ("newly_failed", "Newly failed"),
        ("regressed", "Regressed"),
        ("recovered", "Recovered"),
        ("improved", "Improved"),
    ):
        lines += ["", f"### {title}", "", *case_table(data["cases"][name], "")]
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


def write(data, root=benchmark.ROOT):
    directory = Path(root) / suite.path_definition(data["path"])["reports"]
    stem = f"{data['candidate']['run_id']}__vs__{data['baseline']['run_id']}"
    json_path = directory / f"{stem}.json"
    write_json(json_path, data)
    markdown_path = directory / f"{stem}.md"
    markdown_path.write_text(markdown(data), encoding="utf-8")
    return json_path, markdown_path
