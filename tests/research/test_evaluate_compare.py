"""Keep baseline comparisons explicit about matching and per-entry changes."""

import json

import pytest

from research.evaluate import compare, suite
from research.ocr_eval import benchmark

MANIFEST = {
    "configuration_name": "local-speed",
    "split": "development",
    "suite": {"selection_sha256": "s"},
    "configuration": {"scan_options": {}},
}


def row(key, status="completed", coverage=1.0, valid=True, error=None, **extra):
    score = None if status != "completed" else {"coverage": coverage, "valid": valid}
    return {
        "key": key,
        "status": status,
        "score": score,
        "error": error,
        "label": "injection",
        "detection": {"verdict": "flagged"},
        **extra,
    }


def write_run(
    root,
    run_id,
    rows,
    *,
    manifest=MANIFEST,
    coverage=0.9,
    accuracy=0.5,
    implementation=None,
    host=None,
):
    directory = root / "runs/evaluations" / run_id
    directory.mkdir(parents=True)
    report = {
        "configurations": {
            "local-speed": {
                "rows": rows,
                "groups": [
                    {
                        "facet": "content",
                        "label": "web_page",
                        "images": len(rows),
                        "word_weighted_coverage": coverage,
                        "failed": sum(r["status"] == "failed" for r in rows),
                        "detection": {"accuracy": accuracy},
                    }
                ],
            }
        }
    }
    (directory / "report.json").write_text(json.dumps(report))
    return {
        "kind": suite.SUMMARY_KIND,
        "run_id": run_id,
        "manifest": manifest,
        "implementation": implementation or {"commit": "c1", "dirty": False},
        "host": host or {"platform": "fixture"},
        "operations": {"wall_seconds": 10.0, "peak_rss_bytes": 100},
        "metrics": {
            "completed": sum(r["status"] == "completed" for r in rows),
            "word_weighted_coverage": coverage,
            "image_rates": {"reference_pass": 0.5},
            "detection": {"recall": accuracy, "false_positive_rate": 0.1},
            "cost": {"estimated_usd": 1.0},
        },
        "local_artifacts": f"runs/evaluations/{run_id}",
        "report_sha256": benchmark.digest(directory / "report.json"),
    }


@pytest.fixture
def baseline(tmp_path):
    return tmp_path, write_run(
        tmp_path,
        "base",
        [
            row("a"),
            row("b", coverage=0.5, valid=False),
            row("c", "failed", error="timeout"),
            row("d"),
            row("e", coverage=0.8, valid=False),
            row("f", label="benign", detection={"verdict": "flagged"}),
        ],
    )


def test_cases_are_classified_and_sorted_by_change_size(baseline):
    root, base = baseline
    run = write_run(
        root,
        "run",
        [
            row("a", coverage=0.6, valid=False, detection={"verdict": "not_flagged"}),
            row("b", coverage=1.0),
            row("c"),
            row("d", "failed", error="refused"),
            row("e", coverage=0.9, valid=False),
            row("f", label="benign", detection={"verdict": "not_flagged"}),
        ],
        coverage=0.95,
        accuracy=0.75,
    )
    data = compare.compare(base, run, root)
    assert data["matched"] is True
    assert data["case_counts"] == {
        "newly_failed": 1,
        "recovered": 1,
        "regressed": 1,
        "improved": 2,
        "detection_regressed": 2,
        "detection_improved": 2,
        "detection_changed": 0,
    }
    assert data["cases"]["newly_failed"][0]["error"] == "refused"
    assert [item["key"] for item in data["cases"]["improved"]] == ["b", "e"]
    assert data["cases"]["regressed"][0]["delta"] == pytest.approx(-0.4)
    assert [i["key"] for i in data["cases"]["detection_regressed"]] == ["a", "d"]
    assert [i["key"] for i in data["cases"]["detection_improved"]] == ["c", "f"]
    coverage = next(
        r for r in data["aggregates"] if r["metric"] == "word coverage (tolerant)"
    )
    assert coverage["delta"] == pytest.approx(0.05)
    assert data["contents"][0]["delta"] == pytest.approx(0.05)
    assert data["contents"][0]["accuracy_delta"] == pytest.approx(0.25)


def test_markdown_shows_rates_deltas_and_case_sections(baseline):
    root, base = baseline
    run = write_run(
        root,
        "run",
        [row("a", coverage=0.6, valid=False), *[row(k) for k in "bcdef"]],
        coverage=0.95,
    )
    text = compare.markdown(compare.compare(base, run, root))
    assert "| word coverage (tolerant) | 90.00% | 95.00% | +5.00 pp |" in text
    assert "| attacks flagged (recall) | 50.00% | 50.00% | +0.00 pp |" in text
    assert "| `a` | 100.00% | 60.00% |" in text
    assert "Same inputs: yes" in text
    assert "### Detection now wrong" in text
    assert "## Value versus complexity" in text


def test_non_matched_and_cross_host_comparisons_are_labeled(baseline):
    root, base = baseline
    run = write_run(
        root,
        "run",
        [row(k) for k in "abcd"],
        manifest={**MANIFEST, "suite": {"selection_sha256": "other"}},
        host={"platform": "other"},
    )
    data = compare.compare(base, run, root)
    assert data["matched"] is False
    assert data["differences"] == ["suite.selection_sha256"]
    assert data["case_counts"]["recovered"] == 1  # only shared entries compare
    text = compare.markdown(data)
    assert "Same inputs: NO" in text
    assert "Not a direct comparison" in text
    assert "time and resources are not directly comparable" in text


def test_missing_baseline_report_compares_aggregates_only(baseline):
    root, base = baseline
    run = write_run(root, "run", [row(k) for k in "abcdef"])
    (root / "runs/evaluations/base/report.json").unlink()
    data = compare.compare(base, run, root)
    assert data["cases"] is None and data["contents"] == []
    assert "not on this machine" in compare.markdown(data)
    report = root / "runs/evaluations/run/report.json"
    report.write_text(report.read_text() + " ")
    with pytest.raises(ValueError, match="differs from its run summary"):
        compare.compare(base, run, root)


def test_dirty_runs_ask_for_a_manual_code_surface(baseline):
    root, base = baseline
    run = write_run(
        root,
        "run",
        [row(k) for k in "abcdef"],
        implementation={"commit": "c2", "dirty": True},
    )
    surface = compare.compare(base, run, root)["code_surface"]
    assert surface["available"] is False
    assert "manually" in surface["reason"]


def test_comparison_is_written_into_the_run_directory(baseline):
    root, base = baseline
    run = write_run(root, "run", [row(k) for k in "abcdef"])
    directory = root / "runs/evaluations/run"
    json_path, markdown_path = compare.write(
        compare.compare(base, run, root), directory
    )
    assert json_path == directory / "comparison.json"
    assert markdown_path.read_text().startswith("# Comparison with the baseline")
