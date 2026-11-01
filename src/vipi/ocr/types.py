"""Provider-independent OCR recognition contract and native region records."""

from typing import Protocol

import numpy as np
from PIL import Image


class OcrEngine(Protocol):
    def recognize(self, image: Image.Image) -> dict:
        """Return text and regions in the supplied raster's coordinates."""
        ...


def box_region(text, polygon, confidence, level="word", line_id=None):
    return {
        "text": text,
        "polygon": np.asarray(polygon, dtype=float).tolist(),
        "confidence": float(confidence),
        "level": level,
        "line_id": line_id,
    }
