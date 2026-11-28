"""Find text lines in a background image for the editor's text selection.

Only the text detection of the smallest local OCR model (PP-OCRv6 tiny, about
2 MB) runs, on one thread: it returns where text lines are, nothing is read.
On a laptop CPU this takes a few hundred milliseconds per image (ADR 0093), so
the editor can ask for it in the background as soon as an image is added. The
engine is loaded once and shared; results are cached per image.
"""

import hashlib
from io import BytesIO
import threading

import numpy as np
from PIL import Image, UnidentifiedImageError

MODEL = "ppocr-v6-tiny"
SETUP_HINT = "Run `vipi setup --ocr-mode speed` to find text in background images."

_lock = threading.Lock()  # one detection at a time keeps the load to one thread
_engine = None
_cache = {}  # image SHA-256 -> list of line polygons


class Unavailable(RuntimeError):
    """The tiny OCR model or the OCR runtime is not installed."""


def _detector():
    global _engine
    if _engine is None:
        from vipi.config import cache_directory
        from vipi.ocr.engines import RapidEngine

        try:
            _engine = RapidEngine(MODEL, cache_directory() / "ocr", threads=1)
        except (ValueError, FileNotFoundError, ImportError) as error:
            raise Unavailable(f"{error} {SETUP_HINT}") from None
    return _engine.ocr.text_det


def find_lines(image_png):
    """Text line polygons [[[x, y], …4 corners], …] in image pixels."""
    key = hashlib.sha256(image_png).hexdigest()
    if key in _cache:
        return _cache[key]
    try:
        with Image.open(BytesIO(image_png)) as image:
            pixels = np.asarray(image.convert("RGB"))[:, :, ::-1]  # BGR for OpenCV
    except (UnidentifiedImageError, OSError):
        raise ValueError("The image could not be decoded.") from None
    with _lock:
        result = _detector()(np.ascontiguousarray(pixels))
    boxes = getattr(result, "boxes", None)
    lines = (
        []
        if boxes is None
        else [
            [[round(float(x), 1), round(float(y), 1)] for x, y in box] for box in boxes
        ]
    )
    _cache[key] = lines
    return lines
