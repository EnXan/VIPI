"""Keep benchmark failures visible and preserve production routing."""

import hashlib
import json
from types import SimpleNamespace

import pytest
from PIL import Image

from research.ocr_eval import benchmark
from research.ocr_eval import benchmark_report
from research.ocr_eval.benchmark_report import grouped, score_result, summarize
from research.ocr_eval.evaluation.metrics import compare_words


def test_worker_uses_selected_product_configuration_and_keeps_failures(
    tmp_path, monkeypatch
):
    rows = []
    for index in range(2):
        path = tmp_path / f"research/dataset/images/{index}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fixture")
        rows.append(
            {
                "key": str(index),
                "image": f"images/{index}.png",
                "image_sha256": benchmark.digest(path),
            }
        )
    calls = []

    class Session:
        metadata = {"provider": "fixture"}

        def __init__(self, **kwargs):
            calls.append(kwargs)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    def scan(path, *, options, session, provider, on_event):
        if path.name == "0.png":
            raise ValueError("fixture failure")
        artifacts = tmp_path / "artifacts"
        artifacts.mkdir()
        (artifacts / "result.json").write_text("{}")
        on_event({"run_id": "fixture"})
        ocr = SimpleNamespace(
            artifacts=artifacts, elapsed_seconds=0.25, cost={"estimated_usd": 0}
        )
        return SimpleNamespace(ocr=ocr, options=options, provider=provider)

    def record(result):
        return {
            "verdict": "injection_detected",
            "injection_probability": 0.9,
            "threshold": 0.8,
            "ocr_incomplete": False,
            "signals": {},
            "errors": [],
            "detection_seconds": 0.5,
            "detection_cost": {"estimated_usd": 0.001},
        }

    monkeypatch.setattr(benchmark, "ROOT", tmp_path)
    monkeypatch.setattr(benchmark, "OcrSession", Session)
    monkeypatch.setattr(benchmark, "scan_image", scan)
    monkeypatch.setattr(benchmark, "file_record", record)
    monkeypatch.setattr(benchmark, "prepare_provider", lambda name, path: name)
    output = tmp_path / "benchmark"
    benchmark.worker(output, "cloud-google", rows)
    saved = [
        json.loads(path.read_text())
        for path in sorted((output / "rows").glob("*.json"))
    ]
    assert calls == [
        {
            "mode": "quality",
            "model": "google-cloud-vision",
            "decision_provider": "openai",
        }
    ]
    assert [row["status"] for row in saved] == ["failed", "completed"]
    assert saved[0]["error"] == "fixture failure"
    assert saved[1]["pipeline_seconds"] == 0.25
    assert saved[1]["detection"] == {
        "verdict": "injection_detected",
        "injection_probability": 0.9,
        "threshold": 0.8,
        "ocr_incomplete": False,
        "errors": [],
        "seconds": 0.5,
        "cost": {"estimated_usd": 0.001},
    }
    assert saved[1]["result_sha256"] == benchmark.digest(
        tmp_path / "artifacts/result.json"
    )
    assert not (output / "current.json").exists()


def test_selection_retains_reference_scope_labels_and_unique_keys(evaluation_dataset):
    rows = benchmark.selection(evaluation_dataset)
    assert [row["key"] for row in rows] == ["0", "1", "2"]
    assert rows[0]["reference_words"] == 1
    assert rows[1]["reference_words"] == 2
    assert rows[0]["scope"] == "source_declared_text"
    assert (rows[0]["label"], rows[0]["content"]) == ("injection", "web_page")
    assert rows[0]["obfuscation"] == ["low_contrast"]
    assert all(len(row["image_sha256"]) == 64 for row in rows)
    assert "text" not in rows[0]


def test_selection_keeps_entries_without_reference_text_for_detection(
    evaluation_dataset,
):
    path = evaluation_dataset / "research/dataset/catalog.json"
    entries = json.loads(path.read_text())
    entries[1]["ocr_reference"] = None
    path.write_text(json.dumps(entries))
    rows = benchmark.selection(evaluation_dataset)
    assert [row["key"] for row in rows] == ["0", "1", "2"]
    assert rows[1]["reference_sha256"] is None
    assert (rows[1]["reference_words"], rows[1]["scope"]) == (0, None)


def test_selection_file_freezes_order(tmp_path, evaluation_dataset):
    dataset_repository = evaluation_dataset
    Image.new("RGB", (16, 12), "black").save(
        dataset_repository / "research/dataset/images/1.png"
    )
    rows = benchmark.selection(dataset_repository)
    selected = [
        rows[0],
        next(row for row in rows[1:] if row["image_sha256"] != rows[0]["image_sha256"]),
    ]
    specification = {"keys": [row["key"] for row in selected]}
    path = tmp_path / "selection.json"
    path.write_text(json.dumps(specification))

    actual, record = benchmark.selection_from_file(path, dataset_repository)

    assert actual == selected
    assert len(record["keys_sha256"]) == 64

    specification["keys"] = list(reversed(specification["keys"]))
    path.write_text(json.dumps(specification))
    with pytest.raises(ValueError, match="catalog order"):
        benchmark.selection_from_file(path, dataset_repository)


def test_main_manifest_contains_only_requested_configurations(tmp_path, monkeypatch):
    selected = [{"key": "ocr_eval:fixture", "image_sha256": "a" * 64}]
    runs = []
    monkeypatch.setattr(benchmark, "selection", lambda: selected)
    monkeypatch.setattr(benchmark, "provenance", lambda: {})
    monkeypatch.setattr(benchmark, "evaluation_policy", lambda: {})
    monkeypatch.setattr(
        benchmark,
        "run_configuration",
        lambda directory, configuration, rows, cancel, **reuse: runs.append(
            (directory, configuration, rows, reuse)
        ),
    )

    output = tmp_path / "cloud-only"
    benchmark.main([str(output), "--configuration", "cloud-google"])

    manifest = json.loads((output / "manifest.json").read_text())
    assert list(manifest["configurations"]) == ["cloud-google"]
    assert runs == [
        (
            output / "cloud-google",
            "cloud-google",
            selected,
            {"provenance_record": {}, "reuse_from": None},
        )
    ]


def test_provenance_tolerates_unavailable_macos_sysctl_fields(tmp_path, monkeypatch):
    for path in (
        "research/catalog.py",
        "research/ocr_eval/benchmark.py",
        "uv.lock",
        "research/dataset.json",
        "research/dataset/catalog.json",
    ):
        file = tmp_path / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text("{}")
    monkeypatch.setattr(benchmark.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(benchmark.platform, "platform", lambda: "fixture-platform")
    monkeypatch.setattr(benchmark, "version", lambda name: "fixture")
    monkeypatch.setattr(
        benchmark.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=1, stdout="", stderr="permission denied"
        ),
    )
    monkeypatch.setattr(
        benchmark.subprocess, "check_output", lambda *args, **kwargs: "fixture-commit"
    )

    result = benchmark.provenance(tmp_path)

    assert result["hardware"] == {
        key: None
        for key in (
            "machdep.cpu.brand_string",
            "hw.memsize",
            "hw.physicalcpu",
            "hw.logicalcpu",
        )
    }
    assert result["hardware_unavailable"] == list(result["hardware"])


REFERENCED = {"label": "benign", "reference_sha256": "r"}


def scored_row(matched, total, exact=None, *, conflict=False):
    coverage = matched / total
    exact = matched if exact is None else exact
    return {
        "status": "completed",
        "label": "benign",
        "reference_sha256": "r",
        "reference_words": total,
        "elapsed_seconds": 2.0,
        "cost_estimated_usd": 0.01,
        "score": {
            "matched": matched,
            "total": total,
            "coverage": coverage,
            "valid": matched == total and not conflict,
            "group_conflicts": int(conflict),
            "exact_matched": exact,
            "exact_coverage": exact / total,
            "exact_valid": exact == total and not conflict,
        },
    }


def test_summary_uses_all_planned_images_and_separates_word_and_image_averages():
    rows = [
        scored_row(4, 5, 3),
        scored_row(1, 1, conflict=True),
        {**REFERENCED, "status": "failed", "reference_words": 10, "elapsed_seconds": 4},
        {
            **REFERENCED,
            "status": "completed",
            "reference_words": 2,
            "elapsed_seconds": 1,
        },
        {**REFERENCED, "status": "unattempted", "reference_words": 3},
        {
            "status": "completed",
            "label": "benign",
            "reference_sha256": None,
            "reference_words": 0,
            "elapsed_seconds": 0,
        },
    ]
    summary = summarize(rows)
    assert summary["images"] == 6
    assert summary["referenced"] == 5
    assert summary["attempted"] == 5
    assert summary["scored"] == 2
    assert summary["failed"] == 1
    assert summary["unscored_completed"] == 1
    assert summary["word_weighted_coverage"] == 5 / 6
    assert summary["mean_image_coverage"] == 0.9
    assert summary["all_planned_word_coverage_lower_bound"] == 5 / 21
    assert summary["image_rates"]["at_least_80"] == 2 / 5
    assert summary["image_rates"]["coverage_100"] == 1 / 5
    assert summary["image_rates"]["reference_pass"] == 0
    assert summary["group_conflict_images"] == 1
    assert summary["word_weighted_exact_coverage"] == 4 / 6
    assert summary["time"]["image_seconds_total"] == 9
    assert summary["cost"]["estimated_usd"] is None
    assert summary["cost"]["recorded_estimate_subtotal"] == 0.02
    assert summary["cost"]["unknown_images"] == 3


def test_success_threshold_does_not_round_coverage_up_to_80():
    summary = summarize([scored_row(7999, 10000)])
    assert summary["counts"]["at_least_80"] == 0


def test_grouped_facets_overlap_without_duplicating_content_denominator():
    row = {
        **scored_row(1, 1),
        "label": "benign",
        "content": "web_page",
        "scope": "primary_visible_payload",
        "techniques": [],
        "obfuscation": ["small_font", "blur"],
    }
    groups = grouped([row])
    assert sum(g["images"] for g in groups if g["facet"] == "content") == 1
    assert sum(g["images"] for g in groups if g["facet"] == "obfuscation") == 2
    assert next(g for g in groups if g["facet"] == "label")["images"] == 1


def test_final_score_matches_existing_evaluator_for_ordered_text():
    reference = {"text": "One two three", "reading_order_known": True, "regions": []}
    step = {
        "id": "1",
        "index": 1,
        "label": "Original",
        "text": "One too three",
        "regions": [],
    }
    result = {"text": step["text"], "regions": [], "variants": [step]}
    expected, _, _ = compare_words(reference, result["text"], [])
    actual = score_result(reference, result)
    assert actual["matched"] == expected["matched"]
    assert actual["exact_matched"] == expected["exact"]["matched"]
    assert actual["valid"] == expected["valid"]


def test_unordered_reference_is_scored_from_text_without_word_positions():
    def region(text):
        return {"text": text, "input_polygon": [[0, 0], [10, 0], [10, 10], [0, 10]]}

    reference = {
        "text": "",
        "reading_order_known": False,
        "regions_are_independent": True,
        "regions": [region("Grand Opening"), region("Sale"), region("Sale")],
    }
    text_only = {"text": "Sale  Grand Openinq", "regions": [], "variants": []}
    score = score_result(reference, text_only)
    # Region order is free; a small typo is tolerated; one "Sale" read covers one region
    assert score["matched"] == 3 and score["total"] == 4
    assert score["exact_matched"] == 2
    assert score["valid"] is False
    swapped = {"text": "Opening Grand Sale Sale", "regions": [], "variants": []}
    # Word order inside one region still matters
    assert score_result(reference, swapped)["matched"] == 3


def test_group_conflicts_are_reported_without_failing_the_reference():
    def region(text, left, right):
        return {
            "text": text,
            "input_polygon": [[left, 0], [right, 0], [right, 10], [left, 10]],
        }

    reference = {
        "text": "Alpha Beta",
        "reading_order_known": False,
        "regions_are_independent": True,
        "regions": [region("Alpha", 0, 20), region("Beta", 100, 120)],
    }
    result = {
        "text": "Alpha Beta",
        "regions": [region("Alpha Beta", 0, 120)],
        "variants": [],
    }
    score = score_result(reference, result)
    assert score["matched"] == score["total"] == 2
    # Positions only diagnose merged groups; they do not change the score, so
    # providers with and without word positions are scored alike (ADR 0068).
    assert score["group_conflicts"] == 1
    assert score["valid"] is True


def test_report_scores_ocr_and_detection_and_excludes_private_artifact_paths(
    tmp_path, monkeypatch
):
    selected = {
        "key": "fixture",
        "id": "fixture",
        "label": "injection",
        "content": "web_page",
        "scope": "source_declared_text",
        "reference_sha256": "r",
        "reference_words": 1,
        "techniques": [],
        "obfuscation": [],
    }
    unreferenced = {
        **selected,
        "key": "plain",
        "id": "plain",
        "label": "benign",
        "scope": None,
        "reference_sha256": None,
        "reference_words": 0,
    }
    keys = [selected["key"], unreferenced["key"]]
    manifest = {
        "selection": [selected, unreferenced],
        "selection_filter": {
            "description": "Two fixture entries",
            "keys_sha256": hashlib.sha256(
                json.dumps(keys, separators=(",", ":")).encode()
            ).hexdigest(),
        },
        "configurations": {"cloud-google": {}},
        "provenance": {"source_hashes": {}},
        "evaluation_policy": {"version": 4},
        "protocol": "fixture",
    }
    benchmark.write_json(tmp_path / "manifest.json", manifest)
    for key, verdict in (
        ("fixture", "injection_detected"),
        ("plain", "injection_detected"),
    ):
        artifact = tmp_path / "private-artifacts" / key
        result_path = artifact / "result.json"
        benchmark.write_json(
            result_path, {"text": "Alpha", "regions": [], "variants": []}
        )
        benchmark.write_json(
            tmp_path / f"cloud-google/rows/{key}.json",
            {
                "status": "completed",
                "artifacts": str(artifact),
                "result_sha256": benchmark.digest(result_path),
                "elapsed_seconds": 1,
                "cost": {"estimated_usd": 0.01},
                "detection": {
                    "verdict": verdict,
                    "cost": {"estimated_usd": 0.001},
                },
            },
        )
    excluded = {**selected, "key": "excluded", "id": "excluded"}
    monkeypatch.setattr(
        benchmark_report, "selection", lambda: [selected, excluded, unreferenced]
    )
    monkeypatch.setattr(
        benchmark_report,
        "catalog",
        lambda: SimpleNamespace(
            reference=lambda identifier: {
                "text": "Alpha",
                "regions": [],
                "reading_order_known": True,
            }
        ),
    )
    data = benchmark_report.report(tmp_path)
    measured = data["configurations"]["cloud-google"]
    row, plain = measured["rows"]
    assert row["score"]["valid"]
    assert plain["score"] is None and plain["unscored_reason"] == "No reference text."
    assert row["run_id"] == "fixture"
    assert "artifacts" not in row
    assert row["cost_estimated_usd"] == pytest.approx(0.001)  # OCR usage + detector
    assert data["inference_complete"] is True
    summary = measured["summary"]
    assert (summary["images"], summary["referenced"]) == (2, 1)
    assert summary["image_rates"]["reference_pass"] == 1
    assert summary["detection"]["recall"] == 1
    assert summary["detection"]["false_positive_rate"] == 1
    assert summary["detection"]["accuracy"] == 0.5
    text = benchmark_report.markdown(data)
    assert "# Evaluation: 2 Two fixture entries" in text
    assert "| All images | 2 | 1/1 (100.00%) | 1/1 (100.00%) | 50.00% | 0 | 0 / 0 / 2 |" in text
    result_path = tmp_path / "private-artifacts/fixture/result.json"
    result_path.write_text("{}")
    with pytest.raises(ValueError, match="Saved output changed"):
        benchmark_report.report(tmp_path)


def test_detection_counts_missing_results_as_neither_detected_nor_cleared():
    rows = [
        {
            "status": "completed",
            "label": "injection",
            "detection": {"verdict": "injection_detected"},
            "ocr_incomplete": True,
        },
        {
            "status": "completed",
            "label": "jailbreak",
            "detection": {"verdict": None},
        },
        {"status": "failed", "label": "injection"},
        {
            "status": "completed",
            "label": "benign",
            "detection": {"verdict": "no_injection_detected"},
            "ocr_incomplete": False,
        },
    ]
    found = benchmark_report.detection_summary(rows)
    assert found["attacks"] == {
        "images": 3,
        "injection_detected": 1,
        "no_injection_detected": 0,
        "no_result": 2,
        "ocr_incomplete": {"incomplete": 1, "complete": 0, "unjudged": 1},
    }
    assert found["recall"] == 1 / 3
    assert found["false_positive_rate"] == 0
    assert found["accuracy"] == 0.5
    assert found["no_result"] == 2
    assert found["ocr_incomplete"] == {"incomplete": 1, "complete": 1, "unjudged": 1}


def test_retained_verdicts_from_before_adr_0071_are_mapped_to_the_new_names():
    rows = [
        {"status": "completed", "label": "injection", "detection": {"verdict": v}}
        for v in ("flagged", "not_flagged", "unclear")
    ]
    found = benchmark_report.detection_summary(rows)["attacks"]
    assert (found["injection_detected"], found["no_injection_detected"]) == (1, 1)
    assert found["no_result"] == 1


def test_ocr_incomplete_flag_is_checked_against_reference_coverage():
    def row(flag, matched):
        return {
            "status": "completed",
            "ocr_incomplete": flag,
            "score": {"matched": matched, "total": 4},
        }

    rows = [
        row(True, 2),
        row(True, 4),
        row(False, 4),
        row(False, 3),
        row(None, 4),
        {"status": "completed", "ocr_incomplete": True, "score": None},
    ]
    assert benchmark_report.ocr_incomplete_check(rows) == {
        "flag_true_reference_incomplete": 1,
        "flag_true_reference_complete": 1,
        "flag_false_reference_complete": 1,
        "flag_false_reference_incomplete": 1,
        "unjudged": 1,
    }


def test_resume_preserves_timing_checkpoint_and_does_not_rescan_interrupted_image(
    tmp_path,
):
    benchmark.write_json(
        tmp_path / "current.json", {"key": "ocr_eval:unfinished", "status": "running"}
    )
    benchmark.write_json(tmp_path / "invocations.json", [{"elapsed_seconds": 10}])
    benchmark.write_json(tmp_path / "invocation-current.json", {"elapsed_seconds": 5})
    benchmark.retain_interrupted_progress(tmp_path)
    history = json.loads((tmp_path / "invocations.json").read_text())
    assert sum(row["elapsed_seconds"] for row in history) == 15
    assert history[-1]["interrupted"] is True
    attempt = json.loads((tmp_path / "rows/ocr_eval-unfinished.json").read_text())
    assert attempt["status"] == "failed"
    assert attempt["elapsed_seconds"] is None
    assert not (tmp_path / "current.json").exists()
    benchmark.retain_interrupted_progress(tmp_path)
    assert json.loads((tmp_path / "invocations.json").read_text()) == history
    terminal = tmp_path / "rows/ocr_eval-finished.json"
    benchmark.write_json(terminal, {"key": "ocr_eval:finished", "status": "completed"})
    before = terminal.read_bytes()
    benchmark.write_json(
        tmp_path / "current.json", {"key": "ocr_eval:finished", "status": "running"}
    )
    benchmark.retain_interrupted_progress(tmp_path)
    assert terminal.read_bytes() == before


def test_partial_usage_includes_successful_calls_without_pricing_missing_responses(
    tmp_path,
):
    from vipi.config import GOOGLE_OCR_MODEL

    (tmp_path / "steps.jsonl").write_text(
        json.dumps({"preprocessing": {"usage": {"units": 1}}}) + "\n"
    )
    (tmp_path / "events.jsonl").write_text(
        "\n".join(json.dumps({"type": "ocr_started"}) for _ in range(3))
    )
    benchmark.write_json(tmp_path / "decisions/1/request.json", {})
    benchmark.write_json(
        tmp_path / "decisions/1/response.json",
        {
            "estimated_usd": 0.002,
            "attempts": 2,
            "response": {"usage": {"input_tokens": 20_000}},
        },
    )
    benchmark.write_json(tmp_path / "decisions/2/request.json", {})
    usage = benchmark_report.retained_usage(tmp_path, GOOGLE_OCR_MODEL)
    assert usage["cost_recorded_subtotal_usd"] == 0.0035
    assert usage["ocr_api_calls"] == 3
    assert usage["decision_api_calls"] == 2
    assert usage["decision_http_attempts"] == 2
    assert usage["unreported_requests"] == 3
    assert usage["retry_cost_uncertain"] is True
    assert len(usage["partial_usage_hashes"]) == 4
    summary = summarize(
        [{**REFERENCED, "status": "failed", "reference_words": 1, **usage}]
    )
    assert summary["cost"]["estimated_usd"] is None
    assert summary["cost"]["recorded_estimate_subtotal"] == 0.0035
    assert summary["counts"]["at_least_80"] == 0
