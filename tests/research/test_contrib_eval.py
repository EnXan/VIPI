"""Keep contribution splits grouped/disjoint and baseline freshness explicit."""

import json
import subprocess

import pytest

from research.contrib_eval import runs, splits, suite
from research.contrib_eval.__main__ import main


def entry(key, stratum, *tokens):
    return {"key": key, "stratum": stratum, "image_sha256": key, "tokens": list(tokens)}


def test_filename_family_strips_only_trailing_obfuscation_tokens():
    tokens = {"none", "low-contrast", "base64", "mirrored-text", "rotated-text"}
    assert splits.filename_family("images/a_b_task_low-contrast.png", tokens) == (
        "a_b_task"
    )
    assert splits.filename_family("images/a_b_task_none.png", tokens) == "a_b_task"
    assert (
        splits.filename_family(
            "images/p_121_benign_rotated-text_mirrored-text.png", tokens
        )
        == "p_121_benign"
    )
    assert splits.filename_family("images/release_notes.png", tokens) == (
        "release_notes"
    )


def test_shared_tokens_merge_groups_transitively_across_catalogs():
    entries = [
        entry("ocr_eval:a", "ocr_eval:x", "image:1", "ocr_content:g"),
        entry("ocr_eval:b", "ocr_eval:x", "image:2", "ocr_content:g"),
        entry("detection_eval:c", "detection_eval:injection", "image:2", "payload:p"),
        entry("detection_eval:d", "detection_eval:benign", "image:3", "payload:p"),
        entry("ocr_eval:e", "ocr_eval:x", "image:4", "ocr_content:h"),
    ]
    groups = sorted(splits.group_entries(entries))
    assert groups == [
        ["detection_eval:c", "detection_eval:d", "ocr_eval:a", "ocr_eval:b"],
        ["ocr_eval:e"],
    ]


def test_assignment_is_deterministic_grouped_and_close_to_fraction():
    entries = [
        entry(
            f"ocr_eval:{index}",
            "ocr_eval:x",
            f"image:{index}",
            f"ocr_content:{index // 2}",
        )
        for index in range(200)
    ]
    first = splits.assign(entries)
    assert first == splits.assign(list(reversed(entries)))
    by_group = {}
    for split, group in first.values():
        by_group.setdefault(group, set()).add(split)
    assert all(len(values) == 1 for values in by_group.values())
    assert sum(split == "test" for split, _ in first.values()) == 40
    assert first != splits.assign(entries, seed="other-seed")


def test_each_stratum_is_split_separately():
    entries = [
        entry(f"ocr_eval:{index}", "ocr_eval:x", f"image:{index}")
        for index in range(10)
    ] + [
        entry(f"detection_eval:{index}", "detection_eval:benign", f"image:d{index}")
        for index in range(5)
    ]
    held = [
        key for key, (split, _) in splits.assign(entries).items() if split == "test"
    ]
    assert sum(key.startswith("ocr_eval:") for key in held) == 2
    assert sum(key.startswith("detection_eval:") for key in held) == 1


def test_duplicate_keys_are_rejected():
    with pytest.raises(ValueError, match="unique keys"):
        splits.assign([entry("a", "s", "image:1"), entry("a", "s", "image:2")])


@pytest.fixture
def manifest_root(tmp_path, monkeypatch):
    for source in (
        "research/dataset.json",
        "research/ocr_eval/catalog.json",
        "research/detection_eval/cases.json",
        "research/splits.json",
        *suite.PATHS["ocr/cloud-default"]["metric_sources"],
        *suite.MODEL_REGISTRIES,
    ):
        path = tmp_path / source
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}" if source.endswith(".json") else "# fixture\n")
    rows = [
        {"key": "ocr_eval:a", "image_sha256": "1", "reference_sha256": "r1"},
        {"key": "ocr_eval:b", "image_sha256": "2", "reference_sha256": "r2"},
    ]
    document = {
        "entries": {
            "ocr_eval:a": {"split": "development", "group": "g1", "image_sha256": "1"},
            "ocr_eval:b": {"split": "test", "group": "g2", "image_sha256": "2"},
        }
    }
    monkeypatch.setattr(
        suite.benchmark, "selection", lambda root: [dict(r) for r in rows]
    )
    monkeypatch.setattr(suite.splits, "load", lambda root: document)
    return tmp_path, rows, document


def write_baseline(root, name, manifest, completed_at):
    directory = root / suite.PATHS["ocr/cloud-default"]["reports"]
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_text(
        json.dumps(
            {
                "kind": suite.SUMMARY_KIND,
                "role": "baseline",
                "run_id": name,
                "completed_at": completed_at,
                "manifest": manifest,
            }
        )
    )


def test_manifest_selects_only_the_requested_split(manifest_root):
    root, _rows, _document = manifest_root
    development = suite.manifest("ocr/cloud-default", "development", root)
    test = suite.manifest("ocr/cloud-default", "test", root)
    assert development["suite"]["entries"] == test["suite"]["entries"] == 1
    assert development["suite"]["selection_sha256"] != test["suite"]["selection_sha256"]


def test_status_reports_none_fresh_and_stale_with_changed_fields(manifest_root):
    root, rows, _document = manifest_root
    assert suite.status("ocr/cloud-default", root=root)["state"] == "none"

    current = suite.manifest("ocr/cloud-default", root=root)
    write_baseline(root, "old.json", {**current, "suite": {}}, "2026-11-01T00:00:00")
    write_baseline(root, "new.json", current, "2026-11-07T00:00:00")
    fresh = suite.status("ocr/cloud-default", root=root)
    assert fresh["state"] == "fresh"
    assert fresh["baseline"]["run_id"] == "new.json"

    rows[0]["reference_sha256"] = "changed"
    (root / "research/ocr_eval/evaluation/metrics.py").write_text("# changed\n")
    stale = suite.status("ocr/cloud-default", root=root)
    assert stale["state"] == "stale"
    assert stale["differences"] == [
        "suite.metric_sha256.research/ocr_eval/evaluation/metrics.py",
        "suite.selection_sha256",
    ]


def test_baselines_of_other_splits_and_candidates_are_ignored(manifest_root):
    root, _rows, _document = manifest_root
    test = suite.manifest("ocr/cloud-default", "test", root)
    write_baseline(root, "test.json", test, "2026-11-07T00:00:00")
    directory = root / suite.PATHS["ocr/cloud-default"]["reports"]
    candidate = suite.manifest("ocr/cloud-default", root=root)
    (directory / "candidate.json").write_text(
        json.dumps(
            {
                "kind": suite.SUMMARY_KIND,
                "role": "candidate",
                "run_id": "candidate",
                "completed_at": "2026-11-07T00:00:00",
                "manifest": candidate,
            }
        )
    )
    assert suite.status("ocr/cloud-default", root=root)["state"] == "none"


def test_changed_image_or_missing_assignment_requires_a_new_split(manifest_root):
    root, rows, document = manifest_root
    rows[0]["image_sha256"] = "other"
    with pytest.raises(ValueError, match="Image changed"):
        suite.manifest("ocr/cloud-default", root=root)
    rows[0]["image_sha256"] = "1"
    del document["entries"]["ocr_eval:b"]
    with pytest.raises(ValueError, match="no split assignment"):
        suite.manifest("ocr/cloud-default", root=root)


def test_unknown_path_and_split_are_rejected(manifest_root):
    root, _rows, _document = manifest_root
    with pytest.raises(ValueError, match="Unknown evaluation path"):
        suite.manifest("detector/jev", root=root)
    with pytest.raises(ValueError, match="Choose split"):
        suite.manifest("ocr/cloud-default", "holdout", root=root)


def test_status_command_exits_nonzero_unless_fresh(monkeypatch, capsys):
    monkeypatch.setattr(
        suite,
        "status",
        lambda path, split: {"state": "none", "path": path, "split": split},
    )
    assert main(["status", "ocr/cloud-default"]) == 1
    assert "no committed baseline" in capsys.readouterr().out


class FakeMonitor:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.result = {
            "started_at": "2026-11-07T00:00:00+00:00",
            "wall_seconds": 2.0,
            "cpu_seconds_lower_bound": 1.5,
            "peak_rss_bytes": 100,
            "sampling_seconds": 0.5,
            "gpu": {"available": False, "reason": "fixture"},
        }
        return False


@pytest.fixture
def run_root(manifest_root, monkeypatch):
    root, rows, document = manifest_root
    calls = []
    state = {"complete": True}

    def fake_main(argv):
        calls.append(argv)
        return 0

    def fake_report(directory):
        return {
            "inference_complete": state["complete"],
            "scored_at": "2026-11-07T12:00:00+00:00",
            "configuration_sources": {
                "cloud-default": {
                    "provenance": {"platform": "fixture", "python": "3.12"}
                }
            },
            "configurations": {
                "cloud-default": {
                    "summary": {
                        "completed": 1,
                        "failed": 0,
                        "time": {"image_seconds_total": 1.0, "invocations": [{}]},
                    }
                }
            },
        }

    monkeypatch.setattr(runs, "ResourceMonitor", FakeMonitor)
    monkeypatch.setattr(runs.benchmark, "main", fake_main)
    monkeypatch.setattr(runs.benchmark_report, "report", fake_report)
    monkeypatch.setattr(
        runs,
        "implementation",
        lambda root: {"commit": "abc", "dirty": False, "diff_sha256": "d"},
    )
    return root, rows, calls, state


def test_baseline_run_freezes_split_keys_and_writes_committable_summary(run_root):
    root, _rows, calls, _state = run_root
    result = runs.run("ocr/cloud-default", "baseline", root=root, run_id="base")
    assert result["state"] == "complete"
    directory = root / "runs/contrib/base"
    selection = json.loads((directory / "selection.json").read_text())
    assert selection["keys"] == ["ocr_eval:a"]
    assert calls == [
        [
            str(directory / "benchmark"),
            "--configuration",
            "cloud-default",
            "--selection-file",
            str(directory / "selection.json"),
        ]
    ]
    summary = json.loads((root / result["summary"]).read_text())
    assert summary["role"] == "baseline"
    assert summary["comparison"] is None
    assert summary["metrics"]["time"] == {"image_seconds_total": 1.0}
    assert summary["operations"]["wall_seconds"] == 2.0
    assert summary["operations"]["gpu"]["available"] is False
    assert summary["local_artifacts"] == "runs/contrib/base"
    assert suite.status("ocr/cloud-default", root=root)["state"] == "fresh"


def test_incomplete_run_writes_no_summary_and_resume_accumulates_operations(
    run_root,
):
    root, _rows, calls, state = run_root
    state["complete"] = False
    assert (
        runs.run("ocr/cloud-default", "baseline", root=root, run_id="r")["state"]
        == "incomplete"
    )
    assert suite.status("ocr/cloud-default", root=root)["state"] == "none"
    state["complete"] = True
    result = runs.run("ocr/cloud-default", "baseline", root=root, run_id="r")
    summary = json.loads((root / result["summary"]).read_text())
    assert len(calls) == 2
    assert len(summary["operations"]["invocations"]) == 2
    assert summary["operations"]["wall_seconds"] == 4.0


def test_candidate_must_match_baseline_unless_mismatch_is_recorded(run_root):
    root, rows, _calls, _state = run_root
    runs.run("ocr/cloud-default", "baseline", root=root, run_id="base")
    matched = runs.run(
        "ocr/cloud-default", "candidate", root=root, run_id="cand", against="base"
    )
    summary = json.loads((root / matched["summary"]).read_text())
    assert summary["comparison"]["matched"] is True
    assert suite.status("ocr/cloud-default", root=root)["baseline"]["run_id"] == (
        "base"
    )

    rows[0]["reference_sha256"] = "changed"
    with pytest.raises(ValueError, match="suite.selection_sha256"):
        runs.run("ocr/cloud-default", "candidate", root=root, against="base")
    recorded = runs.run(
        "ocr/cloud-default",
        "candidate",
        root=root,
        run_id="cand2",
        against="base",
        mismatch_reason="reference fix",
    )
    comparison = json.loads((root / recorded["summary"]).read_text())["comparison"]
    assert comparison["matched"] is False
    assert comparison["differences"] == ["suite.selection_sha256"]
    assert comparison["mismatch_reason"] == "reference fix"


def test_resume_refuses_a_different_request_in_the_same_directory(run_root):
    root, rows, _calls, _state = run_root
    runs.run("ocr/cloud-default", "baseline", root=root, run_id="r")
    rows[0]["reference_sha256"] = "changed"
    with pytest.raises(ValueError, match="different run request"):
        runs.run("ocr/cloud-default", "baseline", root=root, run_id="r")


def test_run_request_validation_and_dry_run_start_nothing(run_root):
    root, _rows, calls, _state = run_root
    with pytest.raises(ValueError, match="confirm-test-split"):
        runs.run("ocr/cloud-default", "baseline", "test", root=root)
    with pytest.raises(ValueError, match="requires --against"):
        runs.run("ocr/cloud-default", "candidate", root=root)
    with pytest.raises(ValueError, match="only to candidate"):
        runs.run("ocr/cloud-default", "baseline", root=root, against="x")
    with pytest.raises(ValueError, match="not found"):
        runs.run("ocr/cloud-default", "candidate", root=root, against="missing")
    planned = runs.run(
        "ocr/cloud-default",
        "baseline",
        "test",
        root=root,
        confirm_test=True,
        dry_run=True,
    )
    assert planned["state"] == "planned"
    assert planned["entries"] == 1
    assert calls == []
    assert not (root / "runs").exists()


def test_test_split_summary_is_marked_as_confirmation(run_root):
    root, _rows, _calls, _state = run_root
    result = runs.run(
        "ocr/cloud-default",
        "baseline",
        "test",
        root=root,
        run_id="t",
        confirm_test=True,
    )
    assert (
        json.loads((root / result["summary"]).read_text())["test_split_confirmation"]
        is True
    )


def test_resource_monitor_measures_this_process():
    pytest.importorskip("psutil")
    with runs.ResourceMonitor(interval=0.01) as monitor:
        sum(range(200_000))
    assert monitor.result["peak_rss_bytes"] > 0
    assert monitor.result["cpu_seconds_lower_bound"] > 0
    assert monitor.result["wall_seconds"] >= 0


def test_implementation_records_dirty_and_untracked_changes(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "a.txt").write_text("a")
    subprocess.run(["git", "add", "a.txt"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "a"],
        cwd=tmp_path,
        check=True,
    )
    clean = runs.implementation(tmp_path)
    assert clean["dirty"] is False
    (tmp_path / "b.txt").write_text("b")
    untracked = runs.implementation(tmp_path)
    assert untracked["dirty"] is True and untracked["untracked_files"] == 1
    (tmp_path / "a.txt").write_text("changed")
    assert runs.implementation(tmp_path)["diff_sha256"] != clean["diff_sha256"]
