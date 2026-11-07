"""Standalone two-times OCR candidate from the original upscale trial."""

from PIL import Image

from vipi.ocr.transforms import View
from vipi.ocr.recovery.layout import group_reading


def recognize_upscaled(original, engine):
    """Recognize a 2x view and map all selected groups to original coordinates."""
    raster = original.resize(
        (original.width * 2, original.height * 2), Image.Resampling.BICUBIC
    )
    view = View(
        id="research-upscale-2x",
        width=raster.width,
        height=raster.height,
        to_input=((0.5, 0, 0), (0, 0.5, 0), (0, 0, 1)),
        backend="pillow",
        method="bicubic",
        factor=2,
    )
    recognized = engine.recognize(raster)
    for region in recognized["regions"]:
        region["input_polygon"] = view.map_polygon(region["polygon"])
    step = {
        "id": "upscale-2x",
        "width": raster.width,
        "height": raster.height,
        **recognized,
    }
    if recognized.get("full_page_text") or not recognized["regions"]:
        text, groups = recognized["text"], []
    else:
        text, groups = group_reading(step, raster, view)
    return {
        "id": "upscale-2x",
        "raster": raster,
        "text": text,
        "groups": groups,
        "step": step,
    }
