"""Confident-token retention and the research two-times OCR probe."""

from collections import Counter
import re

from PIL import Image

from vipi.ocr.transforms import View

from .layout import group_reading


def retained_confident_tokens(incumbent_regions, candidate_text, confidence=0.9):
    """List confident native OCR tokens not present in candidate transcription.

    This conservative experimental check uses no reference text. It can reject
    genuine corrections when the incumbent is confidently wrong.
    """
    old = Counter()
    for region in incumbent_regions:
        score = region.get("confidence")
        if (
            isinstance(score, (int, float))
            and not isinstance(score, bool)
            and confidence <= score <= 1
        ):
            old.update(re.findall(r"\w+", region.get("text", "").casefold()))
    if not old:
        raise ValueError("No confident OCR tokens available for retention check")
    new = Counter(re.findall(r"\w+", candidate_text.casefold()))
    return list((old - new).elements())


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
