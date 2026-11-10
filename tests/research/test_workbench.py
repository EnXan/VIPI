"""The workbench: scan an image and evaluate a configuration against the baseline."""

import io
import json
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from research.evaluate import runs as evaluate_runs
from research.ocr_eval import benchmark
from research.workbench import evaluations
from research.workbench.web import create_app


def wait(predicate, seconds=5):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("condition not reached")


def fake_scanner(tmp_path, verdict="flagged", fail=False):
    calls = []

    def scan(image, *, options, on_event):
        calls.append((image, options))
        on_event({"type": "ocr_started", "run_id": "r1"})
        artifacts = tmp_path / "artifacts"
        (artifacts / "images").mkdir(parents=True, exist_ok=True)
        (artifacts / "images/0001.png").write_bytes(b"png")
        (artifacts / "steps.jsonl").write_text(
            json.dumps({"id": "0001", "label": "upright", "text": "Hello"}) + "\n"
        )
        if fail:
            error = RuntimeError("OCR model missing")
            error.artifacts = artifacts
            raise error
        on_event({"type": "detection_started"})
        detection = SimpleNamespace(
            verdict=verdict,
            review_required=verdict != "not_flagged",
            signals={options.resolved_detector: {"max_score": 0.91}},
            answers=[],
            check_id="c1",
            elapsed_seconds=0.5,
            errors=[],
        )
        ocr = SimpleNamespace(
            artifacts=artifacts,
            run_id="r1",
            elapsed_seconds=1.0,
            ocr_profile="product",
            variants=[{}],
            selection={},
            cost={"estimated_usd": 0.0},
            text="Hello",
        )
        return SimpleNamespace(
            ocr=ocr, detection=detection, detector_model="d1", detector_identity="d1"
        )

    return scan, calls


def upload(client, **form):
    data = {"image": (io.BytesIO(b"image-bytes"), "shot.png"), **form}
    return client.post("/api/scans", data=data, content_type="multipart/form-data")


def test_configurations_are_the_product_options_with_the_product_default(tmp_path):
    client = create_app(repository_root=tmp_path).test_client()
    data = client.get("/api/configurations").json
    assert data["default"] == "local-quality-clef-flash"
    assert data["threshold"] == 80
    assert data["splits"] == ["development", "test"]
    labels = {
        item["id"]: (item["label"], item["paid"]) for item in data["configurations"]
    }
    assert labels["local-speed"] == (
        "Local · Speed OCR · d1 (LiquidAI d1-3B) detector",
        False,
    )
    assert labels["local-quality-clef-flash"][0] == (
        "Local · Quality OCR · Clef-Flash (Cloudflare) detector"
    )
    assert "local-quality" not in labels  # Clef was replaced (ADR 0065)
    assert labels["cloud-google"] == (
        "Cloud · Google Cloud Vision · OpenAI Luna detector",
        True,
    )
    assert labels["cloud-google-jev"] == (
        "Cloud · Google Cloud Vision · Jev detector",
        True,
    )
    assert labels["local-speed-prompt-guard"][0] == (
        "Local · Speed OCR · Prompt Guard 2 (Meta) detector"
    )
    detectors = {item["id"]: item["detector"] for item in data["configurations"]}
    assert detectors["cloud-mistral-jev"] == "jev"
    assert detectors["cloud-mistral"] == "openai"
    assert b"Scan an image" in client.get("/").data


def test_scan_reports_verdict_score_text_and_ocr_passes(tmp_path):
    scan, calls = fake_scanner(tmp_path)
    client = create_app(repository_root=tmp_path, scanner=scan).test_client()
    started = upload(client, configuration="local-speed", threshold="70")
    assert started.status_code == 202
    job_id = started.json["id"]
    wait(lambda: client.get(f"/api/scans/{job_id}").json["state"] == "done")
    job = client.get(f"/api/scans/{job_id}").json
    assert job["result"]["verdict"] == "flagged"
    assert job["result"]["score"] == 0.91
    assert job["result"]["text"] == "Hello"
    assert job["steps"][0]["label"] == "upright"
    assert client.get(job["steps"][0]["image_url"]).data == b"png"
    image, options = calls[0]
    assert image == b"image-bytes"
    assert (options.ocr_mode, options.threshold) == ("speed", 70.0)
    assert client.get(f"/api/scans/{job_id}/steps/../x.png").status_code == 404


def test_scan_failure_keeps_the_error_and_releases_the_lock(tmp_path):
    scan, _ = fake_scanner(tmp_path, fail=True)
    client = create_app(repository_root=tmp_path, scanner=scan).test_client()
    job_id = upload(client).json["id"]
    wait(lambda: client.get(f"/api/scans/{job_id}").json["state"] == "failed")
    job = client.get(f"/api/scans/{job_id}").json
    assert job["error"] == "OCR model missing"
    assert len(job["steps"]) == 1
    assert upload(client).status_code == 202


def test_scan_requests_are_validated_and_one_workload_runs_at_a_time(tmp_path):
    release = threading.Event()

    def slow(image, *, options, on_event):
        release.wait(5)
        raise RuntimeError("stopped")

    client = create_app(repository_root=tmp_path, scanner=slow).test_client()
    assert client.post("/api/scans", data={}).status_code == 400
    assert upload(client, configuration="ocr/cloud").status_code == 400
    assert upload(client, threshold="150").status_code == 400
    assert upload(client).status_code == 202
    assert upload(client).status_code == 409
    release.set()


@pytest.fixture
def evaluation_client(tmp_path, monkeypatch):
    """The workbench with simulated evaluation runs in ``tmp_path``."""
    calls = []

    def fake_run(
        configuration,
        split,
        root,
        *,
        run_id=None,
        confirm_test=False,
        dry_run=False,
        cancel=None,
        reuse_ocr=True,
    ):
        if split == "test" and not confirm_test:
            raise ValueError("pass --confirm-test-split")
        run_id = run_id or f"20261109T000000Z-{configuration}-{split}"
        if dry_run:
            return {
                "run_id": run_id,
                "entries": 3,
                "reusable_ocr": 2,
                "reusable_complete": 1,
            }
        calls.append(run_id)
        directory = evaluate_runs.run_directory(run_id, root)
        directory.mkdir(parents=True, exist_ok=True)
        manifest = {
            "configuration_name": configuration,
            "split": split,
            "suite": {"entries": 3},
        }
        benchmark.write_json(
            directory / "request.json", {"manifest": manifest, "reuse_ocr": reuse_ocr}
        )
        rows = directory / "benchmark" / configuration / "rows"
        rows.mkdir(parents=True, exist_ok=True)
        for index in range(3):
            if cancel is not None and cancel.wait(0.05):
                return {"state": "incomplete"}
            benchmark.write_json(rows / f"{index}.json", {})
        report = {
            "configurations": {
                configuration: {
                    "groups": [
                        {
                            "facet": "content",
                            "label": "web_page",
                            "images": 3,
                            "word_weighted_coverage": 0.9,
                            "detection": {
                                "recall": 1.0,
                                "false_positive_rate": 0.0,
                                "accuracy": 1.0,
                            },
                        }
                    ]
                }
            }
        }
        benchmark.write_json(directory / "report.json", report)
        (directory / "report.md").write_text("# Evaluation\n")
        benchmark.write_json(
            directory / "summary.json",
            {"run_id": run_id, "manifest": manifest, "metrics": {"completed": 3}},
        )
        return {"state": "complete"}

    monkeypatch.setattr(evaluations.runs, "run", fake_run)
    monkeypatch.setattr(
        evaluations.suite,
        "status",
        lambda configuration, split, root: {"state": "none"},
    )
    app = create_app(repository_root=tmp_path, evaluation_runner=fake_run)
    return app.test_client(), tmp_path, calls


def test_evaluation_runs_lists_reports_and_saves_the_baseline(evaluation_client):
    client, root, calls = evaluation_client
    setup = client.get("/api/evaluations/setup?configuration=local-speed").json
    assert setup == {
        "entries": 3,
        "reusable_ocr": 2,
        "reusable_complete": 1,
        "baseline": {
            "state": "none",
            "execution": None,
            "host": None,
            "run_id": None,
            "completed_at": None,
            "differences": [],
        },
        "running": [],
    }
    started = client.post("/api/evaluations", json={"configuration": "local-speed"})
    assert started.status_code == 202
    run_id = started.json["run_id"]
    wait(lambda: client.get(f"/api/evaluations/{run_id}").json["state"] == "complete")
    run = client.get(f"/api/evaluations/{run_id}").json
    assert run["progress"] == {"done": 3, "total": 3}
    assert run["metrics"] == {"completed": 3}
    assert run["contents"][0]["content"] == "web_page"
    assert run["is_baseline"] is False
    assert client.get(run["report_url"]).data == b"# Evaluation\n"
    listing = client.get("/api/evaluations").json["runs"]
    assert [item["run_id"] for item in listing] == [run_id]
    assert listing[0]["metrics"] is None  # the list stays light

    saved = client.post(f"/api/evaluations/{run_id}/baseline")
    assert saved.json["path"] == f"research/baselines/{run_id}.json"
    assert json.loads((root / saved.json["path"]).read_text())["run_id"] == run_id
    assert client.get(f"/api/evaluations/{run_id}").json["is_baseline"] is True


def test_test_split_needs_confirmation_and_unknown_runs_are_404(evaluation_client):
    client, _root, calls = evaluation_client
    refused = client.post("/api/evaluations", json={"split": "test"})
    assert refused.status_code == 400 and "confirm" in refused.json["error"]
    assert calls == []
    assert client.get("/api/evaluations/missing").status_code == 404
    assert client.get("/api/evaluations/..%2Fx").status_code == 404
    assert client.post("/api/evaluations/missing/baseline").status_code == 400


def test_a_stopped_evaluation_resumes_with_the_same_run_id(evaluation_client):
    client, _root, calls = evaluation_client
    run_id = client.post(
        "/api/evaluations", json={"configuration": "local-speed"}
    ).json["run_id"]
    client.post(f"/api/evaluations/{run_id}/stop")
    wait(
        lambda: client.get(f"/api/evaluations/{run_id}").json["state"]
        not in {"running", "stopping"}
    )
    state = client.get(f"/api/evaluations/{run_id}").json["state"]
    assert state in {"stopped", "complete"}
    if state == "stopped":
        assert client.post(f"/api/evaluations/{run_id}/resume").status_code == 202
        wait(
            lambda: client.get(f"/api/evaluations/{run_id}").json["state"] == "complete"
        )
    assert calls[-1] == run_id


def test_benchmark_stop_terminates_the_worker_and_keeps_the_image_unrecorded(
    tmp_path, monkeypatch
):
    cancel = threading.Event()

    class Process:
        exitcode = None

        def __init__(self, target, args):
            self.directory = Path(args[0])
            self.alive = True

        def start(self):
            benchmark.write_json(self.directory / "current.json", {"key": "a"})
            cancel.set()

        def is_alive(self):
            return self.alive

        def join(self, timeout=None):
            pass

        def terminate(self):
            self.alive = False

    monkeypatch.setattr(
        benchmark.multiprocessing,
        "get_context",
        lambda name: SimpleNamespace(Process=Process),
    )
    directory = tmp_path / "local-speed"
    benchmark.run_configuration(
        directory, "local-speed", [{"key": "a"}, {"key": "b"}], cancel
    )
    assert not (directory / "current.json").exists()
    assert list((directory / "rows").glob("*.json")) == []
    history = json.loads((directory / "invocations.json").read_text())
    assert history[0]["cancelled"] is True and history[0]["interrupted"] is True


def test_evaluation_reuses_ocr_unless_the_checkbox_is_off(evaluation_client):
    client, root, _calls = evaluation_client
    for reuse in (True, False):
        started = client.post(
            "/api/evaluations",
            json={
                "configuration": f"local-{'speed' if reuse else 'balanced'}",
                "reuse_ocr": reuse,
            },
        )
        run_id = started.json["run_id"]
        wait(
            lambda: client.get(f"/api/evaluations/{run_id}").json["state"] == "complete"
        )
        request = json.loads(
            (evaluate_runs.run_directory(run_id, root) / "request.json").read_text()
        )
        assert request["reuse_ocr"] is reuse
    page = client.get("/").data
    assert b'id="reuse-ocr" type="checkbox" checked' in page


def test_evaluations_run_in_parallel_and_list_running_local_runs(tmp_path, monkeypatch):
    release = threading.Event()

    def runner(configuration, split, root, *, run_id=None, dry_run=False, **_):
        if dry_run:
            return {"run_id": run_id or f"r-{configuration}", "entries": 3}
        release.wait(5)
        return {"state": "complete"}

    monkeypatch.setattr(evaluations.runs, "run", runner)
    service = evaluations.EvaluationService(tmp_path, runner=runner)
    service.start("local-speed", "development", False)
    service.start("cloud-google", "development", False)
    assert sorted(
        (item["configuration"], item["local"]) for item in service.running()
    ) == [("cloud-google", False), ("local-speed", True)]
    with pytest.raises(RuntimeError, match="already running"):
        service.start("local-speed", "development", False)  # same run ID
    release.set()
    wait(lambda: service.running() == [])
