"""Read OpenStego text from the original RGB samples of a PNG."""

from dataclasses import dataclass
from io import BytesIO
from itertools import islice
from struct import Struct
import unicodedata

import numpy as np
from PIL import Image

from .openstego_random_lsb import RandomLsbReader
from .svg.text import normalize_invisible

LEGACY = "openstego"
RANDOM_LSB = "openstego_random_lsb"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
MARKER = b"OPENSTEGO"
HEADER = Struct("<BIBBBB")
HEADER_BYTES = len(MARKER) + HEADER.size
HEADER_PIXELS = (HEADER_BYTES * 8 + 2) // 3
RANDOM_HEADER_BYTES = HEADER_BYTES + 8  # v2 adds the encryption algorithm field.
INCOMPLETE = {
    "encrypted": "The OpenStego payload is encrypted.",
    "compressed": "The OpenStego payload is compressed and could not be checked.",
    "unsupported": "The OpenStego version or bit depth is unsupported.",
    "malformed": "The OpenStego header contains invalid fields.",
    "unreadable": "The PNG pixels could not be read for OpenStego inspection.",
}


@dataclass(frozen=True)
class OpenStego:
    status: str
    stored_bytes: int | None = None
    text: str = ""
    detector_text: str = ""
    invisible_characters: int = 0
    kind: str = LEGACY

    @property
    def label(self):
        return "OpenStego RandomLSB" if self.kind == RANDOM_LSB else "OpenStego"

    @property
    def incomplete(self):
        if self.status not in INCOMPLETE:
            return ()
        message = INCOMPLETE[self.status]
        if self.kind == RANDOM_LSB:
            message = message.replace("OpenStego", self.label)
        return (message,)

    def report(self, answers=()):
        from .detection.evidence import reading_scores

        return {
            "status": self.status,
            "stored_bytes": self.stored_bytes,
            "characters": len(self.text),
            "invisible_characters": self.invisible_characters,
            "scores": reading_scores(answers, ("ocr", self.kind)),
        }


def read_openstego(source):
    """Return the legacy and RandomLSB readings found in an 8-bit RGB PNG."""
    with BytesIO(source) if isinstance(source, bytes) else open(source, "rb") as file:
        png = file.read(26)
        if (
            png[:8] != PNG_SIGNATURE
            or png[12:16] != b"IHDR"
            or png[24:26] != b"\x08\x02"
        ):
            return ()
        file.seek(0)
        try:
            with Image.open(file, formats=("PNG",)) as image:
                if image.n_frames != 1 or image.width * image.height < HEADER_PIXELS:
                    return ()
                return tuple(
                    reading
                    for reading in (_read_legacy(image), _read_random_lsb(image))
                    if reading is not None
                )
        except (OSError, SyntaxError, ValueError, Image.DecompressionBombError):
            return (OpenStego("unreadable"),)


def _read_legacy(image):
    pixels = np.asarray(list(islice(image.getdata(), HEADER_PIXELS)), dtype=np.uint8)
    header = np.packbits(pixels.ravel() & 1).tobytes()
    if not header.startswith(MARKER):
        return None

    version, length, channel_bits, name_length, compressed, encrypted = (
        HEADER.unpack_from(header, len(MARKER))
    )
    if version != 1 or channel_bits != 1:
        return OpenStego("unsupported")
    start_bit = (HEADER_BYTES + name_length) * 8
    if (
        compressed not in (0, 1)
        or encrypted not in (0, 1)
        or start_bit + length * 8 > image.width * image.height * 3
    ):
        return OpenStego("malformed")
    if encrypted:
        return OpenStego("encrypted", length)
    if compressed:
        return OpenStego("compressed", length)
    samples = np.frombuffer(
        image.tobytes(), dtype=np.uint8, count=length * 8, offset=start_bit
    )
    payload = np.packbits(samples & 1).tobytes()
    return _text_reading(payload, LEGACY)


def _read_random_lsb(image):
    capacity = image.width * image.height * 3
    if capacity < RANDOM_HEADER_BYTES * 8:
        return None

    reader = RandomLsbReader(image)
    if reader.read(len(MARKER)) != MARKER:
        return None
    version, length, depth, name_length, compressed, encrypted = HEADER.unpack(
        reader.read(HEADER.size)
    )
    if version != 2 or not 1 <= depth <= 8:
        return OpenStego("unsupported", kind=RANDOM_LSB)

    # OpenStego reads the fixed header and filename at one bit per sample.
    used_header_bits = (RANDOM_HEADER_BYTES + name_length) * 8
    if (
        compressed not in (0, 1)
        or encrypted not in (0, 1)
        or used_header_bits > capacity
        or used_header_bits + length * 8 > capacity * depth
    ):
        return OpenStego("malformed", kind=RANDOM_LSB)
    if encrypted:
        return OpenStego("encrypted", length, kind=RANDOM_LSB)
    if compressed:
        return OpenStego("compressed", length, kind=RANDOM_LSB)

    reader.read(8 + name_length)  # Skip the algorithm tag and filename.
    reader.start_payload(depth)
    return _text_reading(reader.read(length), RANDOM_LSB)


def _text_reading(payload, kind):
    length = len(payload)
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError:
        return OpenStego("binary", length, kind=kind)
    if any(
        unicodedata.category(character) == "Cc" and character not in "\t\n\r"
        for character in text
    ):
        return OpenStego("binary", length, kind=kind)
    detector_text, invisible = normalize_invisible(text)
    return OpenStego("text", length, text, detector_text, invisible, kind)
