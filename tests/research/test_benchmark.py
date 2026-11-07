"""Keep benchmark failures visible and preserve production routing."""

import hashlib
import json
from types import SimpleNamespace

import pytest
from PIL import Image

from research.ocr_eval import benchmark
from research.ocr_eval import benchmark_report
from research.ocr_eval.benchmark_report import grouped, score_result, summarize
from research.ocr_eval.evaluation.metrics import evaluate


def test_worker_uses_selected_product_configuration_and_keeps_failures(
    tmp_path, monkeypatch
):
    rows = []
    for index in range(2):
        path = tmp_path / f"research/ocr_eval/images/{index}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fixture")
        rows.append(
            {
                "key": f"ocr_eval:{index}",
                "suite": "ocr_eval",
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

        def extract(self, path, on_event):
            if path.name == "0.png":
                raise ValueError("fixture failure")
            artifacts = tmp_path / "artifacts"
            artifacts.mkdir()
            (artifacts / "result.json").write_text("{}")
            on_event({"run_id": "fixture"})
            return SimpleNamespace(
                artifacts=artifacts, elapsed_seconds=0.25, cost={"estimated_usd": 0}
            )

    monkeypatch.setattr(benchmark, "ROOT", tmp_path)
    monkeypatch.setattr(benchmark, "OcrSession", Session)
    output = tmp_path / "benchmark"
    benchmark.worker(output, "cloud-default", rows)
    saved = [
        json.loads(path.read_text())
        for path in sorted((output / "rows").glob("*.json"))
    ]
    assert calls == [{"execution_mode": "cloud"}]
    assert [row["status"] for row in saved] == ["failed", "completed"]
    assert saved[0]["error"] == "fixture failure"
    assert saved[1]["pipeline_seconds"] == 0.25
    assert saved[1]["result_sha256"] == benchmark.digest(
        tmp_path / "artifacts/result.json"
    )
    assert not (output / "current.json").exists()


def test_selection_retains_reference_scope_and_unique_suite_keys(
    dataset_repository, monkeypatch
):
    monkeypatch.setattr(
        benchmark, "catalogs", lambda root: {"ocr_eval": benchmark.OcrCatalog(root)}
    )
    rows = benchmark.selection(dataset_repository)
    assert len(rows) == 3
    assert len({row["key"] for row in rows}) == 3
    assert rows[0]["reference_words"] == 1
    assert rows[1]["reference_words"] == 2
    assert rows[0]["scope"] == "source_declared_text"
    assert all(len(row["image_sha256"]) == 64 for row in rows)
    assert "text" not in rows[0]


def test_selection_file_freezes_order_and_image_hash_splits(
    tmp_path, dataset_repository, monkeypatch
):
    monkeypatch.setattr(
        benchmark, "catalogs", lambda root: {"ocr_eval": benchmark.OcrCatalog(root)}
    )
    Image.new("RGB", (16, 12), "black").save(
        dataset_repository / "research/ocr_eval/images/1.png"
    )
    rows = benchmark.selection(dataset_repository)
    selected = [
        rows[0],
        next(row for row in rows[1:] if row["image_sha256"] != rows[0]["image_sha256"]),
    ]
    specification = {
        "keys": [row["key"] for row in selected],
        "confidence_split": {
            selected[0]["image_sha256"]: "calibration",
            selected[1]["image_sha256"]: "evaluation",
        },
    }
    path = tmp_path / "selection.json"
    path.write_text(json.dumps(specification))

    actual, record = benchmark.selection_from_file(path, dataset_repository)

    assert actual == selected
    assert record["confidence_split"] == specification["confidence_split"]
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
        lambda directory, configuration, rows: runs.append(
            (directory, configuration, rows)
        ),
    )

    output = tmp_path / "cloud-only"
    benchmark.main([str(output), "--configuration", "cloud-default"])

    manifest = json.loads((output / "manifest.json").read_text())
    assert list(manifest["configurations"]) == ["cloud-default"]
    assert runs == [(output / "cloud-default", "cloud-default", selected)]


def test_provenance_tolerates_unavailable_macos_sysctl_fields(tmp_path, monkeypatch):
    for path in (
        "research/detection_eval/evaluation/catalog.py",
        "research/ocr_eval/catalog.json",
        "research/detection_eval/cases.json",
    ):
        file = tmp_path / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text("{}")
    monkeypatch.setattr(benchmark, "ROOT", tmp_path)
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

    result = benchmark.provenance()

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


def scored_row(matched, total, exact=None, *, conflict=False):
    coverage = matched / total
    exact = matched if exact is None else exact
    return {
        "status": "completed",
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
        {"status": "failed", "reference_words": 10, "elapsed_seconds": 4},
        {"status": "completed", "reference_words": 2, "elapsed_seconds": 1},
        {"status": "unattempted", "reference_words": 3},
    ]
    summary = summarize(rows)
    assert summary["images"] == 5
    assert summary["attempted"] == 4
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
    assert summary["cost"]["unknown_images"] == 2


def test_success_threshold_does_not_round_coverage_up_to_80():
    summary = summarize([scored_row(7999, 10000)])
    assert summary["counts"]["at_least_80"] == 0


def test_grouped_facets_overlap_without_duplicating_category_denominator():
    row = {
        **scored_row(1, 1),
        "suite": "detection_eval",
        "category": "benign",
        "scope": "primary_visible_payload",
        "techniques": [],
        "obfuscation": ["small_font", "blur"],
        "family": "anamorpher",
    }
    groups = grouped([row])
    assert sum(g["images"] for g in groups if g["facet"] == "category") == 1
    assert sum(g["images"] for g in groups if g["facet"] == "obfuscation") == 2
    assert next(g for g in groups if g["facet"] == "family")["images"] == 1


def test_final_score_matches_existing_evaluator_and_leaves_unlocated_text_unscored():
    reference = {"text": "One two three", "reading_order_known": True, "regions": []}
    step = {
        "id": "1",
        "index": 1,
        "label": "Original",
        "text": "One too three",
        "regions": [],
    }
    result = {"text": step["text"], "regions": [], "variants": [step]}
    expected = evaluate(reference, result["text"], [], [step], include_effects=False)[
        "final"
    ]
    actual = score_result(reference, result)
    assert actual["matched"] == expected["matched"]
    assert actual["exact_matched"] == expected["exact"]["matched"]
    assert actual["valid"] == expected["valid"]
    assert score_result({**reference, "reading_order_known": False}, result) is None


def test_spatial_score_preserves_group_conflict_despite_complete_word_coverage():
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
    assert score["group_conflicts"] == 1
    assert score["valid"] is False


def test_report_verifies_output_hash_and_excludes_private_artifact_paths(
    tmp_path, monkeypatch
):
    selected = {
        "key": "ocr_eval:fixture",
        "id": "fixture",
        "suite": "ocr_eval",
        "category": "fixture",
        "scope": "source_declared_text",
        "reference_words": 1,
        "techniques": [],
        "obfuscation": [],
        "family": None,
    }
    manifest = {
        "selection": [selected],
        "selection_filter": {
            "description": "One selected difficult image",
            "keys_sha256": hashlib.sha256(
                json.dumps([selected["key"]], separators=(",", ":")).encode()
            ).hexdigest(),
            "confidence_split": None,
        },
        "configurations": {"cloud-default": {}},
        "provenance": {"source_hashes": {}},
        "evaluation_policy": {"version": 4},
        "protocol": "fixture",
    }
    benchmark.write_json(tmp_path / "manifest.json", manifest)
    artifact = tmp_path / "private-artifacts/fixture"
    result_path = artifact / "result.json"
    benchmark.write_json(result_path, {"text": "Alpha", "regions": [], "variants": []})
    benchmark.write_json(
        tmp_path / "cloud-default/rows/ocr_eval-fixture.json",
        {
            "status": "completed",
            "artifacts": str(artifact),
            "result_sha256": benchmark.digest(result_path),
            "elapsed_seconds": 1,
            "cost": {"estimated_usd": 0.01},
        },
    )
    excluded = {**selected, "key": "ocr_eval:excluded", "id": "excluded"}
    monkeypatch.setattr(benchmark_report, "selection", lambda: [selected, excluded])
    monkeypatch.setattr(
        benchmark_report,
        "catalogs",
        lambda: {
            "ocr_eval": SimpleNamespace(
                reference=lambda identifier: {
                    "text": "Alpha",
                    "regions": [],
                    "reading_order_known": True,
                }
            )
        },
    )
    data = benchmark_report.report(tmp_path)
    row = data["configurations"]["cloud-default"]["rows"][0]
    assert row["score"]["valid"]
    assert row["run_id"] == "fixture"
    assert "artifacts" not in row
    assert data["inference_complete"] is True
    assert data["selection_filter"]["description"] == "One selected difficult image"
    assert "1 selected difficult images" in benchmark_report.markdown(data)
    assert "100.00%" in benchmark_report.markdown(data)
    separate = tmp_path / "cloud-trial"
    benchmark.write_json(
        separate / "manifest.json", {**manifest, "protocol": "separate cloud trial"}
    )
    original_row = tmp_path / "cloud-default/rows/ocr_eval-fixture.json"
    benchmark.write_json(
        separate / "cloud-default/rows/ocr_eval-fixture.json",
        json.loads(original_row.read_text()),
    )
    paired = benchmark_report.report(tmp_path, separate)
    assert paired["configuration_sources"]["cloud-default"][
        "manifest_sha256"
    ] == benchmark.digest(separate / "manifest.json")
    benchmark.write_json(
        separate / "manifest.json", {**manifest, "evaluation_policy": {"version": 3}}
    )
    with pytest.raises(ValueError, match="disagree on evaluation_policy"):
        benchmark_report.report(tmp_path, separate)
    result_path.write_text("{}")
    with pytest.raises(ValueError, match="Saved output changed"):
        benchmark_report.report(tmp_path)


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
    summary = summarize([{"status": "failed", "reference_words": 1, **usage}])
    assert summary["cost"]["estimated_usd"] is None
    assert summary["cost"]["recorded_estimate_subtotal"] == 0.0035
    assert summary["counts"]["at_least_80"] == 0
