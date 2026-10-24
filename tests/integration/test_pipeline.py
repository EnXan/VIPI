import json
import threading
import time

import pytest
from PIL import Image

from vipi.ocr.merge import assemble
from vipi.ocr.pipeline import extract
from vipi.storage.ocr import RunStore
from vipi.ocr.transforms import FILTERS, OCR_PROFILE, views_for_size


class EmptyEngine:
    def recognize(self, image):
        return {"text": "", "regions": [], "preprocessing": {"resize": "none"}}


def passes_for_views(width, height, count, filters=FILTERS):
    return [
        (view, name)
        for view in views_for_size(width, height)[:count]
        for name in filters
    ]


@pytest.mark.parametrize("backend", ["cpu", "coreml", "cuda"])
def test_native_workers_receive_budget_and_backend(tmp_path, monkeypatch, backend):
    monkeypatch.setattr("vipi.ocr.runtime.os.cpu_count", lambda: 8)
    monkeypatch.setattr("vipi.ocr.runtime.coreml_available", lambda: True)
    monkeypatch.setattr("vipi.ocr.runtime.cuda_available", lambda: True)
    monkeypatch.setattr(
        "vipi.ocr.pipeline.production_passes_for_size",
        lambda *args: passes_for_views(*args, 4),
    )
    settings = []

    def factory(model, directory, **kwargs):
        settings.append(kwargs)
        return EmptyEngine()

    monkeypatch.setattr("vipi.ocr.pipeline.create_engine", factory)
    image = tmp_path / "input.png"
    Image.new("RGB", (16, 12), "white").save(image)
    result = extract(
        image, "test", runs_dir=tmp_path / "runs", workers=4, backend=backend
    )
    assert settings == [{"backend": backend, "threads": 2}] * 4
    assert result["backend"] == backend and result["threads_per_worker"] == 2
    assert result["elapsed_seconds"] > 0
    assert all(step["timing"]["ocr_seconds"] >= 0 for step in result["variants"])
    status = json.loads(
        (tmp_path / "runs" / result["run_id"] / "status.json").read_text()
    )
    assert status["backend"] == backend and status["threads_per_worker"] == 2


def test_every_pass_is_saved_before_next_ocr(tmp_path):
    image = tmp_path / "input.png"
    Image.new("RGB", (16, 12), "white").save(image)
    store = RunStore(tmp_path / "runs", "test")

    class CheckingEngine(EmptyEngine):
        calls = 0

        def recognize(self, image):
            path = store.directory / "steps.jsonl"
            records = path.read_text().splitlines() if path.exists() else []
            assert len(records) == self.calls
            assert store.events[-1]["type"] == "ocr_started"
            assert (store.directory / store.status["current"]["image"]).is_file()
            self.calls += 1
            return super().recognize(image)

    engine = CheckingEngine()
    result = extract(image, "test", engine=engine, store=store, workers=1)
    assert len(result["variants"]) == engine.calls == 13
    assert result["ocr_profile"] == OCR_PROFILE
    assert len(list((store.directory / "images").glob("*.png"))) == 13
    names = [event["type"] for event in store.events]
    assert names[1:6] == [
        "step_started",
        "image_ready",
        "ocr_started",
        "saving",
        "step_completed",
    ]
    assert names[-2:] == ["assembling", "run_completed"]
    assert store.status["ocr_profile"] == OCR_PROFILE
    assert store.status["completed"] == store.status["total"] == 13
    assert json.loads((store.directory / "result.json").read_text()) == result
    assert (store.directory / "result.txt").read_text() == ""
    restored = RunStore.restore(store.directory)
    assert restored.snapshot()["result"] == result
    replay = list(restored.iter_events(after=len(store.events) - 1))
    assert [event["type"] for event in replay] == ["run_completed"]


def test_failure_retains_steps_without_final_result(tmp_path):
    image = tmp_path / "input.png"
    Image.new("RGB", (20, 10), "white").save(image)
    store = RunStore(tmp_path / "runs", "test")

    class FailingEngine(EmptyEngine):
        calls = 0

        def recognize(self, image):
            self.calls += 1
            if self.calls == 2:
                raise RuntimeError("inference failed")
            return super().recognize(image)

    with pytest.raises(RuntimeError, match="inference failed"):
        extract(image, "test", engine=FailingEngine(), store=store, workers=1)
    snapshot = store.snapshot()
    assert snapshot["state"] == "failed" and snapshot["completed"] == 1
    assert len(snapshot["variants"]) == 1
    assert (store.directory / "images/0001.png").exists()
    assert not (store.directory / "result.json").exists()


def region(text, x):
    polygon = [[x, 10], [x + 30, 10], [x + 30, 25], [x, 25]]
    return {
        "text": text,
        "polygon": polygon,
        "input_polygon": polygon,
        "confidence": 0.001,
        "level": "word",
    }


def test_merge_keeps_disagreements_repeated_positions_and_low_confidence():
    text, regions = assemble(
        [
            {"id": "0001", "regions": [region("hello", 10), region("hello", 100)]},
            {"id": "0002", "regions": [region("hello", 11), region("hallo", 10)]},
        ]
    )
    assert text == "hello hello"
    assert len(regions) == 2
    assert any(item["text"] == "hallo" for item in regions[0]["alternatives"])
    assert len(regions[0]["evidence"]) == 3


def test_interrupted_run_is_restored_as_failed(tmp_path):
    store = RunStore(tmp_path, "test")
    store.status.update(state="ocr", total=170)
    store.emit("ocr_started")
    restored = RunStore.restore(store.directory)
    assert restored.status["state"] == "failed"
    assert restored.events[-1]["type"] == "run_failed"


@pytest.mark.parametrize("workers", [4, 8])
def test_parallel_engines_persist_independently_and_keep_variant_order(
    tmp_path, monkeypatch, workers
):
    image = tmp_path / "input.png"
    Image.new("RGB", (16, 12), "white").save(image)
    monkeypatch.setattr(
        "vipi.ocr.pipeline.production_passes_for_size",
        lambda *args: passes_for_views(*args, workers),
    )
    barrier = threading.Barrier(workers)
    store = RunStore(tmp_path / "runs", "test")
    engines = []
    guard = threading.Lock()

    class CheckingEngine(EmptyEngine):
        def __init__(self):
            self.thread = threading.get_ident()
            self.calls = 0

        def recognize(self, raster):
            assert threading.get_ident() == self.thread
            with store.condition:
                previous = [
                    event
                    for event in store.events
                    if event.get("worker_id") == self.worker_id
                ]
                assert previous[-1]["type"] == "ocr_started"
                assert (
                    sum(event["type"] == "step_completed" for event in previous)
                    == self.calls
                )
            if self.calls == 0:
                barrier.wait(
                    timeout=5
                )  # Cannot succeed with sequential/shared inference.
                if previous[-1]["step"]["id"] == "0001":
                    with store.condition:
                        assert store.condition.wait_for(
                            lambda: store.status["completed"] > 0,
                            timeout=5,
                        )
            self.calls += 1
            return super().recognize(raster)

    def factory(*args):
        instance = CheckingEngine()
        # Worker's thread name ends with its executor slot (zero based).
        instance.worker_id = int(threading.current_thread().name.rsplit("_", 1)[1]) + 1
        with guard:
            engines.append(instance)
        return instance

    kwargs = {} if workers == 4 else {"workers": workers}
    result = extract(image, "test", store=store, engine_factory=factory, **kwargs)
    assert result["workers"] == len(engines) == workers
    assert all(engine.calls > 0 for engine in engines)
    assert sum(engine.calls for engine in engines) == workers * len(FILTERS)
    assert [step["index"] for step in result["variants"]] == list(
        range(1, workers * 5 + 1)
    )
    records = [
        json.loads(line)
        for line in (store.directory / "steps.jsonl").read_text().splitlines()
    ]
    assert records[0]["id"] != "0001"
    assert {step["id"] for step in records} == {
        step["id"] for step in result["variants"]
    }
    assert store.snapshot()["variants"] == result["variants"]
    assert store.status["completed"] == store.status["total"] == workers * 5
    assert store.status["active_steps"] == {}
    assert [event["id"] for event in store.events] == list(
        range(1, len(store.events) + 1)
    )
    for step in result["variants"]:
        assert (store.directory / step["image"]).is_file()
        events = [
            event["type"]
            for event in store.events
            if event.get("step", {}).get("id") == step["id"]
        ]
        assert events == [
            "step_started",
            "image_ready",
            "ocr_started",
            "saving",
            "step_completed",
        ]


def test_parallel_failure_drains_inflight_work_before_terminal_event(
    tmp_path, monkeypatch
):
    image = tmp_path / "input.png"
    Image.new("RGB", (16, 12), "white").save(image)
    monkeypatch.setattr(
        "vipi.ocr.pipeline.production_passes_for_size",
        lambda *args: passes_for_views(16, 12, 4, ("unchanged",)),
    )
    barrier, failed = threading.Barrier(4), threading.Event()
    store = RunStore(tmp_path / "runs", "test")

    class FailingEngine(EmptyEngine):
        def recognize(self, raster):
            barrier.wait(timeout=5)
            if raster.size == (16, 12):
                failed.set()
                raise RuntimeError("parallel inference failed")
            assert failed.wait(timeout=5)
            time.sleep(0.02)
            return super().recognize(raster)

    with pytest.raises(RuntimeError, match="parallel inference failed"):
        extract(
            image, "test", store=store, engine_factory=lambda *args: FailingEngine()
        )
    state = store.snapshot()
    assert state["state"] == "failed" and state["completed"] == 3
    assert len(state["variants"]) == 3 and state["active_steps"] == {}
    assert store.events[-1]["type"] == "run_failed"
    count = len(store.events)
    time.sleep(0.03)
    assert len(store.events) == count
    assert not (store.directory / "result.json").exists()


@pytest.mark.parametrize("workers", [0, 9, -1, 1.5, True, "4.0", "invalid"])
def test_worker_limits_before_creating_a_run(tmp_path, workers):
    with pytest.raises(ValueError, match="between 1 and 8"):
        extract("unused.png", runs_dir=tmp_path / "runs", workers=workers)
    assert not (tmp_path / "runs").exists()
