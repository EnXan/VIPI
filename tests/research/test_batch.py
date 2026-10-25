import json
import threading
import time

import pytest

from research.workbench.batch import Batch
from research.ocr_eval.evaluation.catalog import Catalog
from vipi.ocr.transforms import FILTERS, views_for_size
from research.workbench.web import create_app


def test_selected_images_evaluation_failures_continuation_and_restore(
    dataset_repository, monkeypatch
):
    root = dataset_repository
    index = root / "research/ocr_eval/catalog.json"
    original_index = index.read_bytes()
    monkeypatch.setattr("research.workbench.web.validate_model", lambda *args: None)
    monkeypatch.setattr(
        "vipi.ocr.pipeline.production_passes_for_size",
        lambda *args: [(views_for_size(*args)[0], name) for name in FILTERS],
    )
    entered, release = threading.Event(), threading.Event()
    created = []

    class Engine:
        def __init__(self, index):
            self.index = index
            self.calls = 0

        def recognize(self, image):
            self.calls += 1
            if self.index == 0 and self.calls <= len(FILTERS):
                entered.set()
                assert release.wait(timeout=10)
            if self.index == 0 and self.calls == len(FILTERS) + 1:
                raise RuntimeError("native inference failed")
            text = "background REQUIRED extra" if self.index == 0 else "Missing"
            polygon = [[0, 0], [12, 0], [12, 8], [0, 8]]
            return {
                "text": text,
                "regions": [
                    {
                        "text": text,
                        "polygon": polygon,
                        "confidence": 0.8,
                        "level": "line",
                    }
                ],
                "preprocessing": {},
            }

    def factory(*args):
        engine = Engine(len(created))
        created.append(engine)
        return engine

    client = create_app(
        root / "runs", root / "models", repository_root=root, engine_factory=factory
    ).test_client()
    listing = client.get("/api/datasets").json
    ids = [item["id"] for item in listing["items"]]
    assert client.get(listing["items"][0]["thumbnail_url"]).mimetype == "image/jpeg"
    assert client.get(listing["items"][0]["image_url"]).mimetype == "image/png"
    response = client.post(
        "/api/batches", json={"dataset_ids": ids, "workers": 1, "model": "tesseract"}
    )
    assert response.status_code == 202
    batch_id = response.json["batch_id"]
    try:
        assert entered.wait(timeout=10)
        state = client.get(f"/api/batches/{batch_id}").json
        assert state["state"] == "running" and state["current_run_id"]
        assert state["completed"] == 0
        assert client.post("/api/batches", json={"dataset_ids": ids}).status_code == 409
    finally:
        release.set()
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        state = client.get(f"/api/batches/{batch_id}").json
        if state["state"] == "completed":
            break
        time.sleep(0.01)
    assert state["state"] == "completed" and state["completed"] == 3
    assert (
        state["summary"]["valid"]
        == state["summary"]["invalid"]
        == state["summary"]["errors"]
        == 1
    )
    assert state["summary"]["pending"] == 0
    categories = {item["id"]: item for item in state["summary"]["categories"]}
    assert categories["vpi_bench"]["success_rate"] == 0.5
    assert categories["vpi_bench"]["errors"] == 1
    assert categories["mm_safetybench"]["success_rate"] == 0
    assert state["items"][1]["state"] == "failed"
    assert state["items"][2]["state"] == "completed" and not state["items"][2]["valid"]
    result = client.get(f"/api/runs/{state['items'][0]['run_id']}").json["result"]
    assert result["evaluation"]["valid"] and result["evaluation"]["final"]["valid"]
    assert state["evaluation_policy"]["version"] == 3
    assert state["items"][0]["coverage"] == 1
    assert state["items"][0]["exact_coverage"] == 0
    assert state["items"][0]["exact_valid"] is False
    assert state["summary"]["pass_rate"] == pytest.approx(1 / 3)
    assert state["summary"]["exact_pass_rate"] == 0
    assert result["evaluation"]["reference"]["text"] == "Required"
    assert client.get(f"/api/batches/{batch_id}/report.json").json == state
    restarted = create_app(
        root / "runs", root / "models", repository_root=root
    ).test_client()
    assert restarted.get(f"/api/batches/{batch_id}").json == state
    assert index.read_bytes() == original_index
    # Inference failure discarded the first engine; the third image got a fresh one.
    assert len(created) == 2
    # The single-active-run lock is released after all items, including failures.
    response = client.post("/api/batches", json={"dataset_ids": [ids[0]], "workers": 1})
    assert response.status_code == 202
    second_id = response.json["batch_id"]
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if client.get(f"/api/batches/{second_id}").json["state"] == "completed":
            break
        time.sleep(0.01)
    assert client.get(f"/api/batches/{second_id}").json["state"] == "completed"


@pytest.mark.parametrize(
    "data",
    [
        {},
        {"dataset_ids": []},
        {"dataset_ids": [1]},
        {"dataset_ids": ["unknown"]},
        {"dataset_ids": ["../"]},
        {"dataset_ids": ["unknown"], "workers": 9},
    ],
)
def test_invalid_selection_does_not_create_batch(dataset_repository, monkeypatch, data):
    monkeypatch.setattr("research.workbench.web.validate_model", lambda *args: None)
    client = create_app(
        dataset_repository / "runs", repository_root=dataset_repository
    ).test_client()
    assert client.post("/api/batches", json=data).status_code == 400
    assert not (dataset_repository / "runs/batches").exists()


def test_dataset_api_validation(dataset_repository):
    client = create_app(
        dataset_repository / "runs", repository_root=dataset_repository
    ).test_client()
    for query in (
        "category=unknown",
        "offset=-1",
        "limit=0",
        "limit=999",
        "offset=abc",
    ):
        assert client.get(f"/api/datasets?{query}").status_code == 400
    assert client.get("/api/datasets/unknown/image").status_code == 404
    assert client.get("/api/batches/nope").status_code == 404


def test_interrupted_selection_retains_completed_images(dataset_repository):
    catalog = Catalog(dataset_repository)
    batch = Batch(
        dataset_repository / "runs", catalog, list(catalog.items)[:2], "test", 4
    )
    batch.status["state"] = "running"
    batch.status["items"][0].update(state="completed", valid=True)
    batch.status["items"][1]["state"] = "running"
    batch.status["completed"] = 1
    batch.save()
    restored = Batch.restore(dataset_repository / "runs", batch.id)
    state = restored.snapshot()
    assert state["state"] == "failed"
    assert state["items"][0]["valid"] and state["items"][1]["state"] == "failed"
    assert json.loads((restored.directory / "report.json").read_text()) == state


def test_finished_older_report_gets_categories_without_reprocessing(dataset_repository):
    catalog = Catalog(dataset_repository)
    batch = Batch(dataset_repository / "runs", catalog, list(catalog.items), "test", 4)
    batch.status.update(state="completed", completed=3)
    for item, valid in zip(batch.status["items"], [True, False, True]):
        item.update(state="completed", valid=valid)
    batch.save()
    report = batch.directory / "report.json"
    old_report = json.loads(report.read_text())
    del old_report["summary"]["categories"]
    report.write_text(json.dumps(old_report))

    restored = Batch.restore(dataset_repository / "runs", batch.id).snapshot()
    assert restored["items"] == old_report["items"]
    assert restored["state"] == "completed" and restored["completed"] == 3
    categories = {item["id"]: item for item in restored["summary"]["categories"]}
    assert categories["vpi_bench"]["success_rate"] == 0.5
    assert categories["mm_safetybench"]["success_rate"] == 1
    assert json.loads(report.read_text()) == restored


@pytest.mark.parametrize("backend", ["coreml", "cuda"])
def test_selection_passes_backend_to_each_image(
    dataset_repository, monkeypatch, backend
):
    monkeypatch.setattr("vipi.ocr.runtime.coreml_available", lambda: True)
    monkeypatch.setattr("vipi.ocr.runtime.cuda_available", lambda: True)
    monkeypatch.setattr("vipi.ocr.runtime.os.cpu_count", lambda: 8)
    calls = []

    def extract(*args, **kwargs):
        calls.append(kwargs["backend"])
        return {
            "evaluation": {
                "valid": True,
                "detection": {"coverage": 1, "missing": []},
                "final": {
                    "valid": True,
                    "coverage": 1,
                    "missing": [],
                    "exact": {"valid": True, "coverage": 1, "missing": []},
                },
                "best_step_id": "0001",
                "effects": [],
            }
        }

    monkeypatch.setattr("research.workbench.batch.extract", extract)
    catalog = Catalog(dataset_repository)
    batch = Batch(
        dataset_repository / "runs",
        catalog,
        list(catalog.items),
        "ppocr-v6",
        4,
        backend=backend,
    )
    batch.run(dataset_repository / "runs", dataset_repository / "models", catalog, {})
    assert calls == [backend] * 3
    state = batch.snapshot()
    assert state["state"] == "completed" and state["backend"] == backend
    assert state["threads_per_worker"] == 2


def test_minor_ocr_errors_pass_but_literal_words_fail_in_saved_batch(
    dataset_repository, monkeypatch
):
    monkeypatch.setattr(
        "vipi.ocr.pipeline.production_passes_for_size",
        lambda *size: [(views_for_size(*size)[0], "unchanged")],
    )

    class Engine:
        def recognize(self, image):
            return {
                "text": "Requ1red",
                "regions": [
                    {
                        "text": "Requ1red",
                        "confidence": 0.999,
                        "polygon": [[0, 0], [20, 0], [20, 8], [0, 8]],
                        "level": "word",
                    }
                ],
                "preprocessing": {},
            }

    catalog = Catalog(dataset_repository)
    identifier = next(iter(catalog.items))
    batch = Batch(dataset_repository / "runs", catalog, [identifier], "test", 1)
    batch.run(
        dataset_repository / "runs",
        dataset_repository / "models",
        catalog,
        {},
        lambda *args: Engine(),
    )
    report = batch.snapshot()
    assert report["state"] == "completed"
    assert report["items"][0]["coverage"] == 1
    assert report["items"][0]["exact_coverage"] == 0
    assert report["summary"]["pass_rate"] == 1
    assert report["summary"]["exact_pass_rate"] == 0
    assert json.loads((batch.directory / "report.json").read_text()) == report
    assert Batch.restore(dataset_repository / "runs", batch.id).snapshot() == report


def test_batch_reuses_engines_on_their_own_threads_and_releases_run_cache(
    dataset_repository, monkeypatch
):
    from vipi.ocr.pipeline import extract

    monkeypatch.setattr(
        "vipi.ocr.pipeline.production_passes_for_size",
        lambda *args: [
            (view, name) for view in views_for_size(*args)[:2] for name in FILTERS
        ],
    )
    barrier = threading.Barrier(2)
    created = []

    class Engine:
        def __init__(self):
            self.thread = threading.get_ident()
            self.calls = 0

        def recognize(self, image):
            assert threading.get_ident() == self.thread
            if self.calls == 0:
                barrier.wait(timeout=5)
            self.calls += 1
            return {"text": "", "regions": [], "preprocessing": {}}

    def factory(*args):
        engine = Engine()
        created.append(engine)
        return engine

    catalog = Catalog(dataset_repository)
    batch = Batch(dataset_repository / "runs", catalog, list(catalog.items), "test", 2)
    jobs = {}
    batch.run(
        dataset_repository / "runs",
        dataset_repository / "models",
        catalog,
        jobs,
        factory,
    )
    assert batch.snapshot()["state"] == "completed"
    assert len(created) == 2 and all(engine.calls > 0 for engine in created)
    assert sum(engine.calls for engine in created) == len(catalog.items) * 2 * len(
        FILTERS
    )
    assert jobs == {}
    # A mismatched shared pool is rejected before any partial run gets created.
    from vipi.ocr.engine_pool import EnginePool

    with EnginePool("test", dataset_repository / "models", 2, "cpu", factory) as pool:
        with pytest.raises(ValueError, match="must match"):
            extract(
                catalog.path(next(iter(catalog.items))),
                "test",
                workers=1,
                engine_pool=pool,
                runs_dir=dataset_repository / "other-runs",
            )
    assert not (dataset_repository / "other-runs").exists()
