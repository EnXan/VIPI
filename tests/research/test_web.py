import io
import threading
import time

import pytest
from PIL import Image

from research.workbench.web import create_app


def upload():
    content = io.BytesIO()
    Image.new("RGB", (120, 70), "white").save(content, format="PNG")
    content.seek(0)
    return {"image": (content, "input.png"), "model": "tesseract", "workers": "1"}


def test_model_list_does_not_offer_ppocr_v5(tmp_path):
    response = (
        create_app(tmp_path / "runs", tmp_path / "models")
        .test_client()
        .get("/api/models")
    )

    assert response.status_code == 200
    assert [model["id"] for model in response.json["models"]] == [
        "ppocr-v6",
        "ppocr-v6-small",
        "ppocr-v6-tiny",
        "tesseract",
    ]


def test_live_image_busy_failure_replay_and_restore(tmp_path, monkeypatch):
    monkeypatch.setattr("research.workbench.web.validate_model", lambda *args: None)
    entered, release = threading.Event(), threading.Event()

    class Engine:
        calls = 0

        def recognize(self, image):
            self.calls += 1
            if self.calls == 2:
                raise RuntimeError("deliberate OCR failure")
            entered.set()
            assert release.wait(timeout=10)
            return {
                "text": "visible",
                "regions": [
                    {
                        "text": "visible",
                        "polygon": [[1, 1], [40, 1], [40, 20], [1, 20]],
                        "confidence": 0.5,
                        "level": "word",
                    }
                ],
                "preprocessing": {},
            }

    app = create_app(
        tmp_path / "runs", tmp_path / "models", engine_factory=lambda *args: Engine()
    )
    client = app.test_client()
    response = client.post("/api/runs", data=upload())
    assert response.status_code == 202
    run_id = response.json["run_id"]
    assert entered.wait(timeout=10)
    try:
        state = client.get(f"/api/runs/{run_id}").json
        assert state["state"] == "ocr" and state["completed"] == 0
        assert client.get(state["current"]["image_url"]).mimetype == "image/png"
        assert client.post("/api/runs", data=upload()).status_code == 409
        events = client.get(f"/api/runs/{run_id}/events", buffered=False)
        chunk = next(iter(events.response)).decode()
        assert "event: run_started" in chunk
        events.close()
        assert client.get(f"/api/runs/{run_id}/result.txt").status_code == 409
    finally:
        release.set()
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        state = client.get(f"/api/runs/{run_id}").json
        if state["state"] == "failed":
            break
        time.sleep(0.01)
    assert state["state"] == "failed"
    assert state["variants"][0]["text"] == "visible"
    assert client.get(state["variants"][0]["image_url"]).status_code == 200
    replay = client.get(
        f"/api/runs/{run_id}/events",
        headers={"Last-Event-ID": str(state["event_id"] - 1)},
    ).text
    assert "event: run_failed" in replay and "event: run_started" not in replay
    restarted = create_app(tmp_path / "runs", tmp_path / "models").test_client()
    assert restarted.get(f"/api/runs/{run_id}").json["variants"] == state["variants"]
    assert client.get(f"/api/runs/{run_id}/events?after=-1").status_code == 400
    assert client.get("/api/runs/nope").status_code == 404


def test_upload_validation_and_local_origin(tmp_path, monkeypatch):
    monkeypatch.setattr("research.workbench.web.validate_model", lambda *args: None)
    client = create_app(tmp_path / "runs", tmp_path / "models").test_client()
    assert client.get("/").status_code == 200
    assert client.get("/static/fonts/Geist.ttf").status_code == 200
    assert client.post("/api/runs").status_code == 400
    bad = client.post(
        "/api/runs", data={"image": (io.BytesIO(b"not an image"), "bad.png")}
    )
    assert bad.status_code == 400
    assert (
        client.post(
            "/api/runs", data=upload(), headers={"Origin": "https://example.com"}
        ).status_code
        == 403
    )
    assert client.get("/", base_url="http://example.com").status_code == 400
    assert not list((tmp_path / "runs").glob("*.upload"))


@pytest.mark.parametrize("workers", [None, "8"])
def test_web_worker_selection_and_active_snapshot(tmp_path, monkeypatch, workers):
    monkeypatch.setattr("research.workbench.web.validate_model", lambda *args: None)
    count = 4 if workers is None else int(workers)
    barrier, entered, release = (
        threading.Barrier(count),
        threading.Event(),
        threading.Event(),
    )

    class Engine:
        def recognize(self, image):
            barrier.wait(timeout=5)
            entered.set()
            assert release.wait(timeout=10)
            raise RuntimeError("stop after live snapshot")

    client = create_app(
        tmp_path / "runs", tmp_path / "models", engine_factory=lambda *args: Engine()
    ).test_client()
    data = upload()
    if workers is None:
        data.pop("workers")
    else:
        data["workers"] = workers
    response = client.post("/api/runs", data=data)
    assert response.status_code == 202
    run_id = response.json["run_id"]
    try:
        assert entered.wait(timeout=10)
        state = client.get(f"/api/runs/{run_id}").json
        assert state["workers"] == count and state["state"] == "processing"
        assert len(state["active_steps"]) == count
        assert all(entry["state"] == "ocr" for entry in state["active_steps"].values())
        for entry in state["active_steps"].values():
            assert client.get(entry["step"]["image_url"]).mimetype == "image/png"
    finally:
        release.set()
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if client.get(f"/api/runs/{run_id}").json["state"] == "failed":
            break
        time.sleep(0.01)
    assert client.get(f"/api/runs/{run_id}").json["state"] == "failed"


@pytest.mark.parametrize("workers", ["0", "9", "-1", "4.5", "", "abc"])
def test_web_rejects_invalid_workers_without_job(tmp_path, workers):
    client = create_app(tmp_path / "runs", tmp_path / "models").test_client()
    data = upload()
    data["workers"] = workers
    response = client.post("/api/runs", data=data)
    assert response.status_code == 400 and "between 1 and 8" in response.json["error"]
    assert list((tmp_path / "runs").iterdir()) == []


@pytest.mark.parametrize(
    "backend,model",
    [("unknown", "ppocr-v6"), ("coreml", "tesseract"), ("cuda", "tesseract")],
)
def test_web_rejects_invalid_backend_without_job(tmp_path, monkeypatch, backend, model):
    monkeypatch.setattr("research.workbench.web.validate_model", lambda *args: None)
    client = create_app(tmp_path / "runs").test_client()
    data = upload()
    data.update(backend=backend, model=model)
    response = client.post("/api/runs", data=data)
    assert response.status_code == 400
    assert not list((tmp_path / "runs").iterdir())


@pytest.mark.parametrize("backend", ["coreml", "cuda"])
def test_web_gpu_selection_reaches_the_workers(tmp_path, monkeypatch, backend):
    monkeypatch.setattr("research.workbench.web.validate_model", lambda *args: None)
    monkeypatch.setattr("vipi.ocr.runtime.coreml_available", lambda: True)
    monkeypatch.setattr("vipi.ocr.runtime.cuda_available", lambda: True)
    monkeypatch.setattr("vipi.ocr.runtime.os.cpu_count", lambda: 8)
    entered, release = threading.Event(), threading.Event()
    settings = []

    class Engine:
        def recognize(self, image):
            entered.set()
            assert release.wait(timeout=10)
            raise RuntimeError("stop after runtime snapshot")

    def create(model, directory, **kwargs):
        settings.append(kwargs)
        return Engine()

    monkeypatch.setattr("vipi.ocr.pipeline.create_engine", create)
    client = create_app(tmp_path / "runs").test_client()
    data = upload()
    data.update(backend=backend, model="ppocr-v6", workers="4")
    response = client.post("/api/runs", data=data)
    assert response.status_code == 202
    run_id = response.json["run_id"]
    try:
        assert entered.wait(timeout=10)
        state = client.get(f"/api/runs/{run_id}").json
        assert state["backend"] == backend and state["threads_per_worker"] == 2
    finally:
        release.set()
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        state = client.get(f"/api/runs/{run_id}").json
        if state["state"] == "failed":
            break
        time.sleep(0.01)
    assert state["state"] == "failed"
    assert settings == [{"backend": backend, "threads": 2}] * 4
