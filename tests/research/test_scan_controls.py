import io
import threading
import time

import pytest
from PIL import Image

from research.workbench.web import create_app
from vipi.detection.pipeline import classifier_names, settings
from vipi.ocr.transforms import FILTERS, views_for_size


def upload(**fields):
    content = io.BytesIO()
    Image.new("RGB", (32, 20), "white").save(content, format="PNG")
    content.seek(0)
    return {
        "image": (content, "fixture.png"),
        "workers": "1",
        "model": "test",
        **fields,
    }


def wait_for(client, url):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        state = client.get(url).json
        if state["state"] in {"completed", "failed", "cancelled"}:
            return state
        time.sleep(0.01)
    pytest.fail("Background work did not finish.")


def recognize(image, text="Required"):
    width, height = image.size
    return {
        "text": text,
        "regions": [
            {
                "text": text,
                "polygon": [[0, 0], [width, 0], [width, height], [0, height]],
                "confidence": 1,
                "level": "line",
            }
        ],
        "preprocessing": {},
    }


@pytest.mark.parametrize(
    "models", [["jev", "openai"], ["jev", "prompt-guard"], ["openai", "prompt-guard"]]
)
def test_checklist_runs_only_the_selected_models(tmp_path, monkeypatch, models):
    import json

    monkeypatch.setattr("research.workbench.web.validate_model", lambda *args: None)
    monkeypatch.setattr(
        "vipi.ocr.pipeline.production_passes_for_size",
        lambda *size: [(views_for_size(*size)[0], "unchanged")],
    )
    requested = []

    class Engine:
        def recognize(self, image):
            return recognize(image)

    class Provider:
        identity = "fixture"
        model = "fixture"

        def check(self, payload, image=None):
            return {"status": "completed", "probability": 0.9}

    def factory(name):
        requested.append(name)
        return Provider()

    client = create_app(
        tmp_path / "runs",
        engine_factory=lambda *args: Engine(),
        detector_provider_factory=factory,
    ).test_client()
    response = client.post(
        "/api/runs", data=upload(detection=json.dumps({"text_classifiers": models}))
    )
    assert response.status_code == 202
    run_id = response.json["run_id"]
    assert wait_for(client, f"/api/runs/{run_id}")["state"] == "completed"
    base = f"/api/runs/{run_id}/detections"
    check_id = client.get(base).json["checks"][0]["check_id"]
    state = wait_for(client, f"{base}/{check_id}")
    assert state["state"] == "completed"
    assert set(requested) == set(models)
    assert len(requested) == len(models)
    assert set(state["result"]["signals"]) == set(models)
    assert state["options"]["text_classifiers"] == models


def test_checklist_validation_and_legacy_options():
    assert classifier_names(settings(text_classifier="compare")) == [
        "jev",
        "openai",
        "prompt-guard",
    ]
    assert classifier_names(settings(text_classifier="jev")) == ["jev"]
    assert classifier_names(settings(text_classifiers=[], image_check="openai")) == []
    assert classifier_names(settings(text_classifiers=["openai", "openai"])) == [
        "openai"
    ]
    for value in ("jev", ["compare"], ["unknown"], [None], []):
        with pytest.raises(ValueError):
            settings(text_classifiers=value)


def test_cancel_upload_waits_for_inflight_ocr_and_preserves_partial_steps(
    tmp_path, monkeypatch
):
    import json

    monkeypatch.setattr("research.workbench.web.validate_model", lambda *args: None)
    monkeypatch.setattr(
        "vipi.ocr.pipeline.production_passes_for_size",
        lambda *size: [(views_for_size(*size)[0], name) for name in FILTERS],
    )
    entered, release = threading.Event(), threading.Event()
    calls, providers = [], []

    class Engine:
        def recognize(self, image):
            calls.append(image.size)
            entered.set()
            assert release.wait(10)
            return recognize(image)

    def provider(name):
        providers.append(name)
        raise AssertionError("Cancelled OCR must not start a detector.")

    client = create_app(
        tmp_path / "runs",
        engine_factory=lambda *args: Engine(),
        detector_provider_factory=provider,
    ).test_client()
    response = client.post(
        "/api/runs",
        data=upload(detection=json.dumps({"text_classifiers": ["jev", "openai"]})),
    )
    run_id = response.json["run_id"]
    try:
        assert entered.wait(10)
        assert client.post(f"/api/runs/{run_id}/cancel").status_code == 202
        assert client.get(f"/api/runs/{run_id}").json["cancel_requested"]
        assert client.post("/api/runs", data=upload()).status_code == 409
    finally:
        release.set()
    state = wait_for(client, f"/api/runs/{run_id}")
    assert state["state"] == "cancelled"
    assert state["completed"] == len(state["variants"]) == len(calls) == 1
    assert "error" not in state
    assert providers == []
    assert "event: run_cancelled" in client.get(f"/api/runs/{run_id}/events").text
    checks = client.get(f"/api/runs/{run_id}/detections").json["checks"]
    assert checks[0]["state"] == "cancelled"
    restarted = create_app(tmp_path / "runs").test_client()
    assert restarted.get(f"/api/runs/{run_id}").json["state"] == "cancelled"
    assert client.post(f"/api/runs/{run_id}/cancel").status_code == 200
    assert client.post("/api/runs/unknown/cancel").status_code == 404


@pytest.mark.parametrize("target", ["batch", "current_run"])
def test_cancel_batch_retains_completed_images_and_skips_the_rest(
    dataset_repository, monkeypatch, target
):
    root = dataset_repository
    monkeypatch.setattr("research.workbench.web.validate_model", lambda *args: None)
    monkeypatch.setattr(
        "vipi.ocr.pipeline.production_passes_for_size",
        lambda *size: [(views_for_size(*size)[0], "unchanged")],
    )
    entered, release = threading.Event(), threading.Event()
    calls = []

    class Engine:
        def recognize(self, image):
            calls.append(image.size)
            if len(calls) == 2:
                entered.set()
                assert release.wait(10)
            return recognize(image)

    client = create_app(
        root / "runs", repository_root=root, engine_factory=lambda *args: Engine()
    ).test_client()
    identifiers = client.get("/api/datasets").json["matching_ids"]
    response = client.post(
        "/api/batches", json={"dataset_ids": identifiers, "workers": 1, "model": "test"}
    )
    batch_id = response.json["batch_id"]
    try:
        assert entered.wait(10)
        state = client.get(f"/api/batches/{batch_id}").json
        url = (
            f"/api/batches/{batch_id}/cancel"
            if target == "batch"
            else f"/api/runs/{state['current_run_id']}/cancel"
        )
        assert client.post(url).status_code == 202
        interim = client.get(f"/api/batches/{batch_id}").json
        assert interim["state"] == "running" and interim["cancel_requested"]
    finally:
        release.set()
    state = wait_for(client, f"/api/batches/{batch_id}")
    assert state["state"] == "cancelled" and state["completed"] == 1
    assert state["summary"]["valid"] == 1
    assert state["summary"]["cancelled"] == 2
    assert state["summary"]["errors"] == state["summary"]["pending"] == 0
    assert [item["state"] for item in state["items"]] == [
        "completed",
        "cancelled",
        "cancelled",
    ]
    assert state["items"][2]["run_id"] is None and len(calls) == 2
    restarted = create_app(root / "runs", repository_root=root).test_client()
    assert restarted.get(f"/api/batches/{batch_id}").json == state
    assert client.post(f"/api/batches/{batch_id}/cancel").status_code == 200
    assert client.post("/api/batches/unknown/cancel").status_code == 404
    following = client.post(
        "/api/batches",
        json={"dataset_ids": identifiers[:1], "workers": 1, "model": "test"},
    )
    assert following.status_code == 202
    assert (
        wait_for(client, f"/api/batches/{following.json['batch_id']}")["state"]
        == "completed"
    )


def test_cancel_detection_drains_inflight_calls_and_does_not_start_queued_jobs(
    tmp_path, monkeypatch
):
    import json

    monkeypatch.setattr("research.workbench.web.validate_model", lambda *args: None)
    monkeypatch.setattr(
        "vipi.ocr.pipeline.production_passes_for_size",
        lambda *size: [(views_for_size(*size)[0], "unchanged")],
    )
    monkeypatch.setattr(
        "vipi.detection.pipeline.chunks",
        lambda text: [
            {"text": text, "start": 0, "end": len(text), "partial_context": False}
            for _ in range(8)
        ],
    )
    entered, release, lock = threading.Event(), threading.Event(), threading.Lock()
    calls = []

    class Engine:
        def recognize(self, image):
            return recognize(image)

    class Provider:
        identity = "fixture"
        model = "fixture"

        def check(self, payload, image=None):
            with lock:
                calls.append(payload)
                if len(calls) == 4:
                    entered.set()
            assert release.wait(10)
            return {"status": "completed", "probability": 0.9}

    client = create_app(
        tmp_path / "runs",
        engine_factory=lambda *args: Engine(),
        detector_provider_factory=lambda name: Provider(),
    ).test_client()
    response = client.post(
        "/api/runs",
        data=upload(detection=json.dumps({"text_classifiers": ["jev", "openai"]})),
    )
    run_id = response.json["run_id"]
    try:
        assert entered.wait(10)
        assert client.post(f"/api/runs/{run_id}/cancel").status_code == 202
    finally:
        release.set()
    base = f"/api/runs/{run_id}/detections"
    check_id = client.get(base).json["checks"][0]["check_id"]
    state = wait_for(client, f"{base}/{check_id}")
    assert state["state"] == "cancelled"
    assert len(calls) == len(state["answers"]) == 4
    assert state["total"] == 16
    assert "error" not in state
    assert client.get(f"/api/runs/{run_id}").json["state"] == "completed"
    assert "event: detection_cancelled" in client.get(f"{base}/{check_id}/events").text
    restarted = create_app(tmp_path / "runs").test_client()
    assert restarted.get(f"{base}/{check_id}").json["state"] == "cancelled"
