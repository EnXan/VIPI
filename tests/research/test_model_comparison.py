import io
import json
import time
import subprocess
import sys
import threading
from concurrent.futures import CancelledError

import pytest
from PIL import Image

from research.ocr_eval.evaluation.catalog import Catalog
from research.workbench.batch import Batch
from research.workbench.model_runtime import ModelInitializationError
from research.workbench.ocr_costs import cost_for_result, performance_summary
from research.workbench.web import create_app
from research.workbench.model_runtime import WorkerEngine


def response(text="Required", **preprocessing):
    return {"text": text, "regions": [], "preprocessing": preprocessing}


def test_models_run_sequentially_and_release_engines(dataset_repository):
    catalog = Catalog(dataset_repository)
    events = []

    class Engine:
        def __init__(self, name):
            self.name = name
            events.append((name, "load"))

        def recognize(self, image):
            events.append((self.name, "scan"))
            return response()

        def close(self):
            events.append((self.name, "close"))

    root = dataset_repository / "runs"
    batch = Batch(root, catalog, list(catalog.items), ["ppocr-v6", "tesseract"], 4)
    batch.run(root, root / "models", catalog, {}, lambda name, path: Engine(name))
    report = batch.snapshot()
    assert report["state"] == "completed"
    assert report["total"] == report["completed"] == 6
    assert events == [
        (name, action)
        for name in report["models"]
        for action in ("load", "scan", "scan", "scan", "close")
    ]
    assert [row["model"] for row in report["items"]] == ["ppocr-v6"] * 3 + [
        "tesseract"
    ] * 3
    assert all(
        row["elapsed_seconds"] > 0 and row["scan_seconds"] > 0
        for row in report["items"]
    )
    assert all(row["cost"]["estimated_usd"] == 0 for row in report["items"])
    assert all(
        row["performance"]["measured_images"] == 3 for row in report["model_summaries"]
    )
    assert Batch.restore(root, batch.id).snapshot() == report


def test_initialization_failure_skips_model_and_continues(dataset_repository):
    catalog = Catalog(dataset_repository)
    created = []

    class Engine:
        def recognize(self, image):
            return response()

    def factory(name, directory):
        created.append(name)
        if name == "ppocr-v6":
            raise ModelInitializationError("No usable model runtime")
        return Engine()

    root = dataset_repository / "runs"
    batch = Batch(root, catalog, list(catalog.items), ["ppocr-v6", "tesseract"], 1)
    batch.run(root, root / "models", catalog, {}, factory)
    assert created == ["ppocr-v6", "tesseract"]
    assert batch.status["completed"] == 6
    assert batch.status["model_states"] == {
        "ppocr-v6": "failed",
        "tesseract": "completed",
    }


def test_cancel_does_not_start_next_model(dataset_repository):
    catalog = Catalog(dataset_repository)
    root = dataset_repository / "runs"
    batch = Batch(root, catalog, list(catalog.items), ["ppocr-v6", "tesseract"], 1)
    created = []

    class Engine:
        def recognize(self, image):
            batch.cancel()
            return response()

    def factory(name, directory):
        created.append(name)
        return Engine()

    batch.run(root, root / "models", catalog, {}, factory)
    assert created == ["ppocr-v6"]
    assert batch.status["state"] == "cancelled"
    assert all(item["state"] == "cancelled" for item in batch.status["items"])
    assert batch.status["items"][0]["scan_seconds"] > 0


def test_uploaded_model_comparison_has_text_timing_cost_and_no_reference(
    tmp_path, monkeypatch
):
    monkeypatch.setattr("research.workbench.web.validate_model", lambda *args: None)

    class Engine:
        def recognize(self, image):
            return response("Visible upload text")

    client = create_app(
        tmp_path / "runs", tmp_path / "models", engine_factory=lambda *args: Engine()
    ).test_client()
    image = io.BytesIO()
    Image.new("RGB", (50, 30), "white").save(image, format="PNG")
    image.seek(0)
    started = client.post(
        "/api/runs",
        data={
            "image": (image, "test.png"),
            "models": json.dumps(["ppocr-v6", "tesseract"]),
        },
    )
    assert started.status_code == 202
    identifier = started.json["batch_id"]
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        report = client.get(f"/api/batches/{identifier}").json
        if report["state"] in {"completed", "failed"}:
            break
        time.sleep(0.01)
    assert report["state"] == "completed"
    assert client.get(f"/api/batches/{identifier}/input").mimetype == "image/png"
    assert report["summary"]["total"] == 0
    for item in report["items"]:
        assert item["recognized_text"] == "Visible upload text"
        assert item["valid"] is None
        assert item["elapsed_seconds"] > 0
        assert item["cost"]["estimated_usd"] == 0


@pytest.mark.parametrize(
    "model,usage,amount",
    [
        (
            "gpt-6-luna",
            {
                "input_tokens": 1000,
                "output_tokens": 100,
                "input_tokens_details": {"cached_tokens": 200},
            },
            0.000132,
        ),
        ("google-cloud-vision", {"units": 1}, 0.0015),
        ("mistral-ocr-4-1", {"pages_processed": 1}, 0.004),
    ],
)
def test_cost_estimate_preserves_usage_and_pricing(model, usage, amount):
    result = cost_for_result(
        {"model": model, "variants": [{"preprocessing": {"usage": usage}}]}
    )
    assert result["estimated_usd"] == pytest.approx(amount)
    assert result["usage"] == [usage]
    assert result["source"].startswith("https://")
    assert result["pricing_checked_at"] == "2026-10-25"


def test_unknown_cost_is_not_zero_and_cancelled_executed_call_counts():
    unknown = cost_for_result({"model": "gpt-6-luna", "variants": []})
    assert unknown["estimated_usd"] is None
    report = performance_summary(
        [
            {"state": "completed", "cost": unknown, "elapsed_seconds": 3},
            {
                "state": "cancelled",
                "run_id": "executed",
                "cost": {"estimated_usd": 0.1},
                "elapsed_seconds": 1,
            },
            {"state": "cancelled"},
        ]
    )
    assert report["cost_unknown_images"] == 1
    assert report["estimated_api_cost_usd"] is None
    assert report["known_estimated_api_cost_usd"] == 0.1
    assert report["mean_seconds"] == 2


def test_isolated_worker_reuse_close_and_cancel_during_initialization(
    tmp_path, monkeypatch
):
    from research.workbench import model_runtime

    spawn = subprocess.Popen
    script = """
import json,sys,time
from pathlib import Path
print('VIPI_OCR_RESULT '+json.dumps({'ready':True,'initialization_seconds':2}),flush=True)
for line in sys.stdin:
 request=json.loads(line)
 Path(request['output']).write_text(json.dumps({'text':'Visible','regions':[],'preprocessing':{}}))
 print('VIPI_OCR_RESULT '+json.dumps({'completed':True,'inference_seconds':0.5}),flush=True)
"""
    monkeypatch.setattr(
        model_runtime.subprocess,
        "Popen",
        lambda command, **options: spawn([sys.executable, "-c", script], **options),
    )
    engine = WorkerEngine(
        "test", tmp_path, profile="baseline", backend="cpu", threads=1
    )
    try:
        image = Image.new("RGB", (10, 10))
        assert (
            engine.recognize(image)["preprocessing"]["runtime_initialization_seconds"]
            == 2
        )
        assert (
            engine.recognize(image)["preprocessing"]["runtime_initialization_seconds"]
            == 0
        )
    finally:
        engine.close()
    assert engine.process.poll() is not None

    monkeypatch.setattr(
        model_runtime.subprocess,
        "Popen",
        lambda command, **options: spawn(
            [sys.executable, "-c", "import sys; sys.stdin.read()"], **options
        ),
    )
    loading = WorkerEngine(
        "test", tmp_path, profile="baseline", backend="cpu", threads=1
    )
    errors = []

    def recognize():
        try:
            loading.recognize(image)
        except CancelledError:
            errors.append("cancelled")

    worker = threading.Thread(target=recognize)
    worker.start()
    loading.cancel()
    worker.join(timeout=10)
    loading.close()
    assert not worker.is_alive()
    assert errors == ["cancelled"]


def test_unordered_transcription_without_geometry_is_explicitly_unscored(tmp_path):
    from research.ocr_eval.evaluation.runner import extract

    source = tmp_path / "input.png"
    Image.new("RGB", (50, 30), "white").save(source)

    class Engine:
        def recognize(self, image):
            return response("Visible word")

    result = extract(
        source,
        "test",
        runs_dir=tmp_path / "runs",
        engine=Engine(),
        reference={
            "text": "Visible word",
            "reading_order_known": False,
            "regions": [
                {
                    "text": "Visible word",
                    "input_polygon": [[0, 0], [40, 0], [40, 20], [0, 20]],
                }
            ],
        },
    )
    assert "evaluation" not in result
    assert "without coordinates" in result["evaluation_unavailable"]["reason"]
    assert result["evaluation_unavailable"]["reference"]["text"] == "Visible word"
