"""Compatibility import for the shared product OCR implementation."""

import sys
from vipi.ocr import _layout_footer as _implementation

sys.modules[__name__] = _implementation
