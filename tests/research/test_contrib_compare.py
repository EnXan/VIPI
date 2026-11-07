"""Keep baseline/candidate comparisons explicit about matching and per-case changes."""

import json

import pytest

from research.contrib_eval import compare, suite
from research.ocr_eval import benchmark

MANIFEST = {
    "path": "ocr/cloud-default",
    "split": "development",
    "suite": {"selection_sha256": "s"},
    "configuration": {"benchmark_configuration": {"cloud-default": {}}},
}


def row(key, status="completed", coverage=1.0, valid=True, error=None):
    score = None if status != "completed" else {"coverage": coverage, "valid": valid}
    return {"key": key, "status": status, "score": score, "error": error}


def write_run(
    root,
    run_id,
    role,
    rows,
    *,
    manifest=MANIFEST,
    coverage=0.9,
    against=None,
    implementation=None,
    host=None,
    mismatch_reason=None,
):
    directory = root / "runs/contrib" / run_id
    directory.mkdir(parents=True)
    report = {
        "configurations": {
            "cloud-default": {
                "rows": rows,
                "groups": [
                    {
                        "facet": "category",
                        "label": "ocr_eval/textocr",
                        "images": len(rows),
                        "word_weighted_coverage": coverage,
                        "failed": sum(r["status"] == "failed" for r in rows),
                    }
                ],
            }
        }
    }
    (directory / "report.json").write_text(json.dumps(report))
    summary = {
        "kind": suite.SUMMARY_KIND,
        "role": role,
        "run_id": run_id,
        "manifest": manifest,
        "comparison": None
        if role == "baseline"
        else {"baseline_run_id": against, "mismatch_reason": mismatch_reason},
        "implementation": implementation or {"commit": "c1", "dirty": False},
        "host": host or {"platform": "fixture"},
        "operations": {"wall_seconds": 10.0, "peak_rss_bytes": 100},
        "metrics": {
            "completed": sum(r["status"] == "completed" for r in rows),
            "word_weighted_coverage": coverage,
            "image_rates": {"reference_pass": 0.5},
            "cost": {"estimated_usd": 1.0},
        },
        "local_artifacts": f"runs/contrib/{run_id}",
        "report_sha256": benchmark.digest(directory / "report.json"),
    }
    reports = root / "research/ocr_eval/reports/contrib"
    reports.mkdir(parents=True, exist_ok=True)
    (reports / f"{run_id}.json").write_text(json.dumps(summary))


@pytest.fixture
def runs_root(tmp_path):
    write_run(
        tmp_path,
        "base",
        "baseline",
        [
            row("a"),
            row("b", coverage=0.5, valid=False),
            row("c", "failed", error="timeout"),
            row("d"),
            row("e", coverage=0.8, valid=False),
        ],
    )
    return tmp_path


def test_cases_are_classified_and_sorted_by_change_size(runs_root):
    write_run(
        runs_root,
        "cand",
        "candidate",
        [
            row("a", coverage=0.6, valid=False),
            row("b", coverage=1.0),
            row("c"),
            row("d", "failed", error="refused"),
            row("e", coverage=0.9, valid=False),
        ],
        coverage=0.95,
        against="base",
    )
    data = compare.compare("base", "cand", runs_root)
    assert data["matched"] is True
    assert data["case_counts"] == {
        "newly_failed": 1,
        "recovered": 1,
        "regressed": 1,
        "improved": 2,
    }
    assert data["cases"]["newly_failed"][0]["error"] == "refused"
    assert [item["key"] for item in data["cases"]["improved"]] == ["b", "e"]
    assert data["cases"]["regressed"][0]["delta"] == pytest.approx(-0.4)
    coverage = next(
        r for r in data["aggregates"] if r["metric"] == "word coverage (tolerant)"
    )
    assert coverage["delta"] == pytest.approx(0.05)
    assert data["categories"][0]["delta"] == pytest.approx(0.05)


def test_markdown_shows_rates_deltas_and_case_sections(runs_root):
    write_run(
        runs_root,
        "cand",
        "candidate",
        [row("a", coverage=0.6, valid=False), *[row(k) for k in "bcde"]],
        coverage=0.95,
        against="base",
    )
    text = compare.markdown(compare.compare("base", "cand", runs_root))
    assert "| word coverage (tolerant) | 90.00% | 95.00% | +5.00 pp |" in text
    assert "| `ocr_eval:a`" not in text and "| `a` | 100.00% | 60.00% |" in text
    assert "Matched inputs: yes" in text
    assert "## Value versus complexity" in text


def test_non_matched_and_cross_host_comparisons_are_labeled(runs_root):
    write_run(
        runs_root,
        "cand",
        "candidate",
        [row(k) for k in "abcde"],
        manifest={**MANIFEST, "suite": {"selection_sha256": "other"}},
        against="base",
        host={"platform": "other"},
        mismatch_reason="new references",
    )
    data = compare.compare("base", "cand", runs_root)
    assert data["matched"] is False
    assert data["differences"] == ["suite.selection_sha256"]
    text = compare.markdown(data)
    assert "Matched inputs: NO" in text
    assert "Recorded reason: new references" in text
    assert "Not a direct performance comparison." in text
    assert "time and resources are not directly comparable" in text


def test_candidate_must_belong_to_the_named_baseline(runs_root):
    write_run(runs_root, "other", "baseline", [row(k) for k in "abcde"])
    write_run(
        runs_root, "cand", "candidate", [row(k) for k in "abcde"], against="other"
    )
    with pytest.raises(ValueError, match="was run against other"):
        compare.compare("base", "cand", runs_root)
    with pytest.raises(ValueError, match="baseline run with a candidate"):
        compare.compare("cand", "base", runs_root)
    with pytest.raises(ValueError, match="not found"):
        compare.compare("base", "missing", runs_root)


def test_missing_or_changed_local_report_is_rejected(runs_root):
    write_run(runs_root, "cand", "candidate", [row(k) for k in "abcde"], against="base")
    report = runs_root / "runs/contrib/cand/report.json"
    report.write_text(report.read_text() + " ")
    with pytest.raises(ValueError, match="differs from the committed summary"):
        compare.compare("base", "cand", runs_root)
    report.unlink()
    with pytest.raises(ValueError, match="not available locally"):
        compare.compare("base", "cand", runs_root)


def test_different_case_sets_are_rejected(runs_root):
    write_run(runs_root, "cand", "candidate", [row(k) for k in "abcd"], against="base")
    with pytest.raises(ValueError, match="different cases"):
        compare.compare("base", "cand", runs_root)


def test_dirty_runs_ask_for_a_manual_code_surface(runs_root):
    write_run(
        runs_root,
        "cand",
        "candidate",
        [row(k) for k in "abcde"],
        against="base",
        implementation={"commit": "c2", "dirty": True},
    )
    surface = compare.compare("base", "cand", runs_root)["code_surface"]
    assert surface["available"] is False
    assert "manually" in surface["reason"]


def test_written_comparison_is_ignored_by_baseline_status(runs_root, monkeypatch):
    write_run(runs_root, "cand", "candidate", [row(k) for k in "abcde"], against="base")
    json_path, markdown_path = compare.write(
        compare.compare("base", "cand", runs_root), runs_root
    )
    assert json_path.name == "cand__vs__base.json"
    assert markdown_path.read_text().startswith("# Contribution comparison")
    found = list(
        suite.baseline_summaries("ocr/cloud-default", "development", runs_root)
    )
    assert [summary["run_id"] for _, summary in found] == ["base"]
