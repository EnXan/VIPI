import subprocess
import sys
import threading
from concurrent.futures import CancelledError

import pytest
from PIL import Image

from vipi.ocr.costs import cost_for_result
from research.workbench.model_runtime import WorkerEngine


def response(text="Required", **preprocessing):
    return {"text": text, "regions": [], "preprocessing": preprocessing}


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
