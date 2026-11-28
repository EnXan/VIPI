"""QR codes and barcodes that `vipi.barcodes` decodes (ADR 0084).

A code layer is visible: the browser draws the module image this module makes
with zxing-cpp, the library VIPI reads codes with. The read-back decodes the
final raster as VIPI does and matches its `Format: text` lines.
"""

from io import BytesIO

import numpy as np
from PIL import Image

# zxing-cpp formats that can be created; text formats first, numeric ones after.
FORMATS = {
    "QRCode": "text",
    "MicroQRCode": "text",
    "RMQRCode": "text",
    "DataMatrix": "text",
    "Aztec": "text",
    "PDF417": "text",
    "CompactPDF417": "text",
    "MicroPDF417": "text",
    "MaxiCode": "text",
    "Code128": "text",
    "Code39": "text",
    "Code93": "text",
    "Telepen": "text",
    "EAN13": "digits",
    "EAN8": "digits",
    "UPCA": "digits",
    "UPCE": "digits",
    "ITF": "digits",
    "DataBar": "digits",
}


def _zxing():
    import zxingcpp

    return zxingcpp


def options():
    return [{"id": name, "content": content} for name, content in FORMATS.items()]


def create(format_id, text):
    """The barcode object, or ValueError with zxing-cpp's reason."""
    if format_id not in FORMATS:
        raise ValueError(f"Unknown code format: {format_id!r}.")
    if not isinstance(text, str) or not text:
        raise ValueError("A code needs content.")
    zxingcpp = _zxing()
    try:
        return zxingcpp.create_barcode(text, getattr(zxingcpp.BarcodeFormat, format_id))
    except Exception as error:  # noqa: BLE001 - zxing-cpp raises plain errors
        raise ValueError(f"{format_id} cannot hold this content: {error}") from None


def module_png(format_id, text):
    """PNG with one pixel per module and the format's quiet zone."""
    barcode = create(format_id, text)
    image = Image.fromarray(np.array(_zxing().write_barcode_to_image(barcode, scale=1)))
    buffer = BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue(), str(barcode.format)


def reader_label(format_id, text):
    """The line `vipi.barcodes.read_codes` writes for this code."""
    return f"{create(format_id, text).format}: {text.strip()}"
