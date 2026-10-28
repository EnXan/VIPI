"""Optional document-VLM OCR adapters for local evaluation runs.

These adapters deliberately use each model project's document pipeline rather
than VIPI's multi-view OCR profile. Their dependencies stay optional so the
standard scanner environment does not acquire document-conversion runtimes.
"""

from __future__ import annotations

import os
import sys
import tempfile
from importlib.metadata import version
from pathlib import Path

from PIL import Image

from vipi.config import GRANITE_DOCLING_MODEL, PADDLEOCR_VL_MODEL

OCR_MODEL_LABELS = {
    PADDLEOCR_VL_MODEL: "PaddleOCR-VL 1.6 · full-page document pipeline",
    GRANITE_DOCLING_MODEL: "Granite-Docling 258M · Docling pipeline",
}


def installed_models():
    """Return model options that can be loaded in the current Python runtime."""
    from importlib.util import find_spec

    available = {
        PADDLEOCR_VL_MODEL: find_spec("paddleocr") is not None,
        GRANITE_DOCLING_MODEL: find_spec("docling") is not None,
    }
    return [
        {
            "id": model,
            "label": label,
            "available": available[model],
            "reason": None
            if available[model]
            else f"Install the optional runtime for {label}.",
            "runtime": "research",
        }
        for model, label in OCR_MODEL_LABELS.items()
    ]


def is_ocr_model(model):
    return model in OCR_MODEL_LABELS


class PaddleOCRVLEngine:
    """Official PaddleOCR-VL 1.6 page-level parsing pipeline."""

    full_page_text = True

    def __init__(self):
        try:
            from paddleocr import PaddleOCRVL
        except ImportError as error:
            raise ValueError(
                "PaddleOCR-VL requires paddleocr[doc-parser]>=3.6.0 and "
                "PaddlePaddle>=3.2.1. See https://www.paddleocr.ai/latest/en/"
                "version3.x/pipeline_usage/PaddleOCR-VL-Apple-Silicon.html."
            ) from error
        options = {"pipeline_version": "v1.6"}
        if sys.platform == "darwin":
            options["device"] = "cpu"
        server_url = os.environ.get("PADDLEOCR_VL_SERVER_URL")
        if server_url:
            options.update(
                vl_rec_backend="mlx-vlm-server",
                vl_rec_server_url=server_url,
                vl_rec_api_model_name=os.environ.get(
                    "PADDLEOCR_VL_API_MODEL", "PaddlePaddle/PaddleOCR-VL-1.6"
                ),
            )
        self.pipeline = PaddleOCRVL(**options)

    def recognize(self, image: Image.Image) -> dict:
        with tempfile.TemporaryDirectory(prefix="vipi-paddle-vl-") as directory:
            image_path = Path(directory) / "input.png"
            image.save(image_path, format="PNG")
            results = self.pipeline.predict(str(image_path))
            markdown_dir = Path(directory) / "markdown"
            markdown_dir.mkdir()
            regions = []
            for result in results:
                result.save_to_markdown(save_path=str(markdown_dir))
                payload = result.json
                payload = payload.get("res", payload)
                for block in payload.get("parsing_res_list", []):
                    region = _box_region(
                        block.get("block_content"), block.get("block_bbox", [])
                    )
                    if region:
                        regions.append(region)
            text = "\n".join(
                path.read_text(encoding="utf-8")
                for path in sorted(markdown_dir.glob("*.md"))
            ).strip()
        return {
            "text": text,
            "regions": regions,
            "full_page_text": True,
            "preprocessing": {
                "pipeline": "PaddleOCRVL(pipeline_version='v1.6').predict",
                "layout_and_page_processing": True,
                "package_versions": {
                    name: version(name) for name in ("paddleocr", "paddlepaddle")
                },
            },
        }


class GraniteDoclingEngine:
    """IBM Granite-Docling through the model's official Docling VLM pipeline."""

    full_page_text = True

    def __init__(self):
        try:
            from docling.datamodel import vlm_model_specs
            from docling.datamodel.base_models import InputFormat
            from docling.datamodel.pipeline_options import VlmPipelineOptions
            from docling.document_converter import (
                DocumentConverter,
                ImageFormatOption,
            )
            from docling.pipeline.vlm_pipeline import VlmPipeline
        except ImportError as error:
            raise ValueError(
                "Granite-Docling requires the optional Docling runtime."
            ) from error

        options = VlmPipelineOptions()
        model_spec = "GRANITEDOCLING_TRANSFORMERS"
        if hasattr(vlm_model_specs, model_spec):
            options.vlm_options = getattr(vlm_model_specs, model_spec)
        self.pipeline_spec = model_spec
        self.converter = DocumentConverter(
            format_options={
                InputFormat.IMAGE: ImageFormatOption(
                    pipeline_cls=VlmPipeline,
                    pipeline_options=options,
                )
            }
        )

    def recognize(self, image: Image.Image) -> dict:
        with tempfile.TemporaryDirectory(prefix="vipi-granite-docling-") as directory:
            image_path = Path(directory) / "input.png"
            image.save(image_path, format="PNG")
            document = self.converter.convert(source=image_path).document
            text = document.export_to_markdown().strip()
            page = next(iter(document.pages.values()), None)
            regions = []
            if page and page.size:
                for item, _level in document.iterate_items():
                    value = getattr(item, "text", None)
                    provenance = getattr(item, "prov", None) or []
                    if not value or not provenance:
                        continue
                    bbox = provenance[0].bbox.to_top_left_origin(page.size.height)
                    scaled = bbox.normalized(page.size)
                    region = _box_region(
                        value,
                        [
                            scaled.l * image.width,
                            scaled.t * image.height,
                            scaled.r * image.width,
                            scaled.b * image.height,
                        ],
                    )
                    if region:
                        regions.append(region)
        return {
            "text": text,
            "regions": regions,
            "full_page_text": True,
            "preprocessing": {
                "pipeline": f"Docling VlmPipeline / {self.pipeline_spec}",
                "input": "original decoded image as lossless PNG",
                "package_versions": {
                    name: version(name) for name in ("docling", "transformers")
                },
            },
        }


def _configure_model_cache(models_dir):
    root = Path(models_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("PADDLE_PDX_CACHE_HOME", str(root / "paddlex"))
    os.environ.setdefault("HF_HOME", str(root / "huggingface"))
    os.environ.setdefault("MODELSCOPE_CACHE", str(root / "modelscope"))


def create_engine(model, models_dir="models/ocr"):
    _configure_model_cache(models_dir)
    if model == PADDLEOCR_VL_MODEL:
        return PaddleOCRVLEngine()
    if model == GRANITE_DOCLING_MODEL:
        return GraniteDoclingEngine()
    raise ValueError(f"Unsupported research OCR model: {model}")


def _box_region(text, box):
    if not isinstance(text, str) or not text.strip() or box is None or len(box) != 4:
        return None
    left, top, right, bottom = (float(value) for value in box)
    if right <= left or bottom <= top:
        return None
    return {
        "text": text,
        "polygon": [
            [left, top],
            [right, top],
            [right, bottom],
            [left, bottom],
        ],
        "confidence": None,
        "level": "block",
    }


def prepare_model(model, models_dir="models/ocr"):
    """Download model assets through the selected upstream pipeline explicitly."""
    create_engine(model, models_dir).recognize(Image.new("RGB", (128, 64), "white"))
