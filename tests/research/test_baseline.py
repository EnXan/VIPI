import json
import io
import time
from pathlib import Path

import pytest
from PIL import Image

from research.ocr_eval.evaluation.profiles import engine_factory_for, validate_profile
from research.ocr_eval.evaluation.runner import extract, reassemble
from research.workbench.batch import Batch
from research.ocr_eval.evaluation.catalog import Catalog
from vipi.ocr.transforms import BASELINE_OCR_PROFILE


@pytest.mark.parametrize(
    "profile,workers", [(None, 1), ("baseline", 1), ("transforms", 4)]
)
def test_cli_uses_recorded_profile_and_single_baseline_worker(
    monkeypatch, profile, workers
):
    from research.workbench.__main__ import main

    calls = []

    def recognize(*args, **kwargs):
        calls.append(kwargs)
        return {"text": "native text"}

    monkeypatch.setattr("research.workbench.__main__.extract", recognize)
    args = ["extract", "image.png"]
    if profile:
        args += ["--ocr-profile", profile]
    assert main(args) == 0
    assert calls[0]["ocr_profile"] == (profile or "baseline")
    assert calls[0]["workers"] == workers


def test_web_defaults_to_one_original_call_and_rejects_invalid_profile(
    tmp_path, monkeypatch
):
    from research.workbench.web import create_app

    calls = []

    class Engine:
        def recognize(self, image):
            calls.append(image.size)
            return {"text": "native text", "regions": [], "preprocessing": {}}

    monkeypatch.setattr("research.workbench.web.validate_model", lambda *args: None)
    client = create_app(
        tmp_path / "runs", engine_factory=lambda *args: Engine()
    ).test_client()

    def upload(**options):
        content = io.BytesIO()
        Image.new("RGB", (37, 23), "white").save(content, format="PNG")
        content.seek(0)
        return {
            "image": (content, "input.png"),
            "model": "test",
            "workers": "8",
            **options,
        }

    response = client.post("/api/runs", data=upload())
    assert response.status_code == 202
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        state = client.get(f"/api/runs/{response.json['run_id']}").json
        if state["state"] in {"completed", "failed"}:
            break
        time.sleep(0.01)
    assert state["state"] == "completed", state
    assert calls == [(37, 23)]
    assert state["workers"] == 1
    assert state["result"]["ocr_profile"] == BASELINE_OCR_PROFILE
    assert state["result"]["text"] == "native text"
    assert (
        client.post("/api/runs", data=upload(ocr_profile="invalid")).status_code == 400
    )
    assert len(calls) == 1


def test_baseline_keeps_pixels_and_raw_text_without_transforms_or_assembly(
    tmp_path, monkeypatch
):
    image = tmp_path / "input.png"
    original = Image.new("RGB", (37, 23), (91, 72, 13))
    original.save(image)
    raw = "  raw\n\nmodel output  "
    calls = []

    def forbidden(*args, **kwargs):
        pytest.fail("Baseline must not invoke VIPI transforms or assembly")

    for name in (
        "production_passes_for_size",
        "render_view",
        "apply_filter",
        "assemble",
    ):
        monkeypatch.setattr(f"vipi.ocr.pipeline.{name}", forbidden)

    class Engine:
        def recognize(self, raster):
            calls.append((raster.size, raster.tobytes()))
            return {"text": raw, "regions": [], "preprocessing": {"pipeline": "native"}}

    result = extract(
        image, "test", engine=Engine(), workers=4, runs_dir=tmp_path / "runs"
    )
    assert calls == [(original.size, original.tobytes())]
    assert result["text"] == raw
    assert result["workers"] == 1
    assert result["ocr_profile"] == BASELINE_OCR_PROFILE
    assert result["assembly_version"] is None
    assert result["preserve_raw_text"] is True
    assert len(result["variants"]) == 1
    replayed = reassemble(result["run_id"], runs_dir=tmp_path / "runs")
    assert replayed["text"] == raw and replayed["assembly_version"] is None


def test_profile_selects_native_backend_and_preserves_injected_engines(
    tmp_path, monkeypatch
):
    calls = []

    def create(*args, **kwargs):
        calls.append(kwargs)

    monkeypatch.setattr("vipi.ocr.engines.create_engine", create)
    for profile, native in (("baseline", True), ("transforms", False)):
        engine_factory_for(profile, workers=1)("ppocr-v6", tmp_path)
        assert calls[-1]["native_pipeline"] is native

    def injected(*args):
        return None

    assert engine_factory_for("baseline", override=injected) is injected
    with pytest.raises(ValueError, match="baseline or transforms"):
        validate_profile("unknown")


def test_baseline_batch_runs_each_selected_image_once_and_records_profile(
    dataset_repository,
):
    catalog = Catalog(dataset_repository)
    calls = []

    class Engine:
        def recognize(self, image):
            calls.append(image.size)
            return {"text": "Required", "regions": [], "preprocessing": {}}

    root = dataset_repository / "runs"
    batch = Batch(root, catalog, list(catalog.items), "test", 4)
    batch.run(root, dataset_repository / "models", catalog, {}, lambda *args: Engine())
    report = json.loads((batch.directory / "report.json").read_text())
    assert report["state"] == "completed"
    assert report["ocr_profile"] == "baseline"
    assert report["workers"] == 1
    assert len(calls) == report["total"] == 3
    assert all(item["ocr_profile"] == BASELINE_OCR_PROFILE for item in report["items"])
    assert all(
        len(item["input_sha256"]) == len(item["reference_sha256"]) == 64
        for item in report["items"]
    )


def test_batch_records_current_source_without_freeze_gate(dataset_repository):
    catalog = Catalog(dataset_repository)
    identifier = next(iter(catalog.items))
    root = dataset_repository / "runs"
    batch = Batch(root, catalog, [identifier], "test", 1)
    before = batch.status["items"][0]["input_sha256"]
    Image.new("RGB", (32, 24), "black").save(catalog.path(identifier))

    class Engine:
        def recognize(self, image):
            assert image.size == (32, 24)
            return {"text": "Required", "regions": [], "preprocessing": {}}

    batch.run(root, dataset_repository / "models", catalog, {}, lambda *args: Engine())
    report = batch.snapshot()
    assert report["items"][0]["state"] == "completed"
    assert report["items"][0]["input_sha256"] != before


def test_docling_uses_lossless_image_input(tmp_path, monkeypatch):
    pytest.importorskip("docling")
    from types import SimpleNamespace
    from research.workbench.ocr_models import GraniteDoclingEngine

    original = Image.new("RGB", (37, 23), (91, 72, 13))
    seen = []

    class Converter:
        def __init__(self, **kwargs):
            seen.append(kwargs["format_options"])

        def convert(self, source):
            assert Path(source).suffix == ".png"
            with Image.open(source) as raster:
                assert raster.size == original.size
                assert raster.tobytes() == original.tobytes()
            return SimpleNamespace(
                document=SimpleNamespace(
                    export_to_markdown=lambda: "native text",
                    pages={},
                )
            )

    monkeypatch.setattr("docling.document_converter.DocumentConverter", Converter)
    output = GraniteDoclingEngine().recognize(original)
    assert output["text"] == "native text"
    assert output["preprocessing"]["input"] == "original decoded image as lossless PNG"
    assert len(seen) == 1
