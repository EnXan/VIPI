"""Compatibility import for the shared product OCR implementation."""

import sys
from vipi.ocr import resolution_retention as _implementation

sys.modules[__name__] = _implementation
