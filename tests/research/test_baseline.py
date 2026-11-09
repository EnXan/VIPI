from pathlib import Path

import pytest
from PIL import Image

from research.ocr_eval.evaluation.profiles import engine_factory_for, validate_profile
from research.ocr_eval.evaluation.runner import extract, reassemble
from vipi.ocr.transforms import BASELINE_OCR_PROFILE


@pytest.mark.parametrize(
    "profile,workers,expected_profile",
    [
        (None, 1, "baseline"),
        ("baseline", 1, "baseline"),
        ("transforms", 4, "transforms"),
    ],
)
def test_cli_uses_recorded_profile_and_profile_worker_count(
    monkeypatch, profile, workers, expected_profile
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
    assert calls[0]["ocr_profile"] == expected_profile
    assert calls[0]["workers"] == workers


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
    for profile, native in (
        ("baseline", True),
        ("transforms", False),
        ("adaptive-jev", True),
    ):
        engine_factory_for(profile, workers=1)("ppocr-v6", tmp_path)
        assert calls[-1]["native_pipeline"] is native

    def injected(*args):
        return None

    assert engine_factory_for("baseline", override=injected) is injected
    with pytest.raises(ValueError, match="baseline, transforms or adaptive-jev"):
        validate_profile("unknown")


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
