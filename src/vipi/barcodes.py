"""Decoded QR and barcode payloads as a detector reading (ADR 0084).

A code's payload is invisible to OCR but is what a phone, scanner or agent
reads. Every code zxing-cpp decodes in the scanned raster becomes one
`Format: text` line of a single reading. Decoded URLs are only checked as
text and never fetched.
"""

from dataclasses import dataclass

from .svg.text import normalize_invisible

READING = "barcode"
INCOMPLETE_FAILED = (
    "Barcode decoding failed ({error}); payloads of codes in the image were "
    "not checked."
)


@dataclass(frozen=True)
class Barcodes:
    """The decoded codes of one raster, ready for detection."""

    formats: tuple[str, ...]
    text: str
    detector_text: str
    invisible_characters: int
    binary: int
    error: str | None = None

    @property
    def incomplete(self):
        if self.error:
            return (INCOMPLETE_FAILED.format(error=self.error),)
        return ()

    def report(self, answers=()):
        """The report's `barcodes` object; `answers` adds the score per reading."""
        from .detection.evidence import reading_scores

        return {
            "formats": list(self.formats),
            "characters": len(self.text),
            "invisible_characters": self.invisible_characters,
            "binary": self.binary,
            "scores": reading_scores(answers, ("ocr", READING)),
        }


def read_codes(raster):
    """Decode every QR code and barcode zxing-cpp finds in a PIL raster."""
    import zxingcpp

    try:
        found = zxingcpp.read_barcodes(raster)
    except Exception as error:  # noqa: BLE001 - reported as incomplete
        return Barcodes((), "", "", 0, 0, str(error) or type(error).__name__)
    lines, binary = [], 0
    for code in found:
        if code.content_type == zxingcpp.ContentType.Binary:
            binary += 1
        elif code.text.strip():
            lines.append((str(code.format), code.text.strip()))
    text = "\n".join(f"{name}: {value}" for name, value in lines)
    detector_text, invisible = normalize_invisible(text)
    return Barcodes(
        formats=tuple(name for name, _ in lines),
        text=text,
        detector_text=detector_text,
        invisible_characters=invisible,
        binary=binary,
    )
