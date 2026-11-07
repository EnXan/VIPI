"""Recovery resource ownership and partial/completed artifact contracts."""

from concurrent.futures import CancelledError
import json
import threading

from PIL import Image
import pytest

from vipi.ocr.recovery.pipeline import extract
from vipi.storage.ocr import RunStore


class Engine:
    def __init__(self, *, fail=False):
        self.fail = fail
        self.closed = 0

    def recognize(self, image):
        if self.fail:
            raise RuntimeError("OCR unavailable")
        return {
            "text": "KEEP",
            "regions": [
                {
                    "text": "KEEP",
                    "confidence": 0.8,
                    "polygon": [[10, 10], [90, 10], [90, 30], [10, 30]],
                }
            ],
        }

    def close(self):
        self.closed += 1


class Pool:
    def __init__(self, engine):
        self.instance = engine
        self.discarded = 0

    def engine(self):
        return self.instance

    def discard_engine(self):
        self.discarded += 1


class Decider:
    provider = "fixture"
    model = "fixture-model"

    def assess(self, *args):
        pytest.fail("The clear route must not request a model decision")


@pytest.fixture
def source(tmp_path, monkeypatch):
    path = tmp_path / "source.png"
    Image.new("RGB", (128, 96), "white").save(path)
    monkeypatch.setattr(
        "vipi.ocr.recovery.selection.route_extended",
        lambda *args: {"route": "no_signal", "signals": [], "unavailable": []},
    )
    return path


@pytest.mark.parametrize("ownership", ["caller", "pipeline", "pool"])
@pytest.mark.parametrize("outcome", ["completed", "cancelled", "failed"])
def test_recovery_preserves_engine_ownership_and_partial_artifacts(
    source, tmp_path, ownership, outcome
):
    engine = Engine(fail=outcome == "failed")
    pool = Pool(engine)
    cancel = threading.Event()

    def on_event(event):
        if outcome == "cancelled" and event["type"] == "step_completed":
            cancel.set()

    store = RunStore(tmp_path / "runs", "fixture", on_event)
    if ownership == "caller":
        options = {"engine": engine}
    elif ownership == "pipeline":
        options = {"engine_factory": lambda *args: engine}
    else:
        options = {"engine_pool": pool}

    if outcome == "completed":
        result = extract(
            source,
            "fixture",
            store=store,
            decider=Decider(),
            cancel_event=cancel,
            **options,
        )
        assert result["text"] == "KEEP"
    else:
        error = CancelledError if outcome == "cancelled" else RuntimeError
        with pytest.raises(error):
            extract(
                source,
                "fixture",
                store=store,
                decider=Decider(),
                cancel_event=cancel,
                **options,
            )

    snapshot = store.snapshot()
    assert snapshot["state"] == outcome
    assert len(snapshot["variants"]) == (0 if outcome == "failed" else 1)
    assert store.events[-1]["type"] == f"run_{outcome}"
    assert (store.directory / "input.png").exists()
    assert (store.directory / "images/0001.png").exists()
    assert (store.directory / "result.json").exists() == (outcome == "completed")
    assert (store.directory / "result.txt").exists() == (outcome == "completed")
    assert engine.closed == (1 if ownership == "pipeline" else 0)
    assert pool.discarded == (1 if ownership == "pool" and outcome == "failed" else 0)


@pytest.mark.parametrize("fail", [False, True])
def test_evaluation_callback_precedes_completion_and_retains_partial_ocr_on_failure(
    source, tmp_path, fail
):
    engine = Engine()
    store = RunStore(tmp_path / "runs", "fixture")
    callbacks = []

    def evaluate(result):
        callbacks.append(result["selection"]["selected_attempt"])
        assert "cost" in result
        assert not (store.directory / "result.json").exists()
        assert store.snapshot()["state"] != "completed"
        assert (
            json.loads((store.directory / "attempts.json").read_text())[0]["text"]
            == "KEEP"
        )
        if fail:
            raise RuntimeError("Evaluation unavailable")
        result["evaluation"] = {"valid": True}

    options = {
        "store": store,
        "decider": Decider(),
        "engine_factory": lambda *args: engine,
        "on_result": evaluate,
    }
    if fail:
        with pytest.raises(RuntimeError, match="Evaluation unavailable"):
            extract(source, "fixture", **options)
        assert store.snapshot()["state"] == "failed"
        assert not (store.directory / "result.json").exists()
    else:
        result = extract(source, "fixture", **options)
        saved = json.loads((store.directory / "result.json").read_text())
        assert saved == json.loads(json.dumps(result))
        assert saved["evaluation"] == {"valid": True}
        assert store.events[-1]["evaluation"] == saved["evaluation"]
        assert store.snapshot()["state"] == "completed"
    assert callbacks == ["0001"]
    assert len(store.snapshot()["variants"]) == 1
    assert engine.closed == 1
