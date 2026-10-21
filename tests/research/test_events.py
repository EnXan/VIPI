from research.workbench.presentation import sse_events
from vipi.storage.ocr import RunStore


def test_sse_adapter_replays_core_events_without_changing_saved_records(tmp_path):
    store = RunStore(tmp_path, "fixture")
    store.emit(
        "step_completed",
        step={"id": "0001", "view_id": "original", "image": "images/0001.png"},
    )
    store.transition("run_completed", state="completed")
    raw = (store.directory / "events.jsonl").read_bytes()
    events = "".join(sse_events(store))
    assert "event: step_completed" in events
    assert f"/api/runs/{store.id}/steps/0001/image" in events
    assert "image_url" not in raw.decode()
    assert (store.directory / "events.jsonl").read_bytes() == raw
    assert "event: step_completed" not in "".join(sse_events(store, after=1))
