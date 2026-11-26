"""Read zsteg-style ASCII candidates from explicitly selected PNG layouts."""

from dataclasses import dataclass
from io import BytesIO
from itertools import islice, product
import re

READING = "png_lsb"
# Match the preview consumed by tools that call zsteg with default settings.
PREVIEW_BYTES = 256
TEXT_RUN = re.compile(rb"[\x20-\x7e\r\n\t]{8,}")
LAYOUT = re.compile(r"b[1-8],(?:r|g|b|rgb|bgr),(?:lsb|msb),(?:xy|yx)")


def validate_layout(layout):
    if not isinstance(layout, str) or not LAYOUT.fullmatch(layout):
        raise ValueError("Use an LSB layout such as b1,rgb,lsb,xy.")
    return layout


@dataclass(frozen=True)
class PngLsb:
    layouts: tuple[str, ...]
    candidates: tuple[tuple[str, str], ...] = ()
    unreadable: bool = False

    @property
    def detector_text(self):
        return "\n".join(f"{layout}: {text}" for layout, text in self.candidates)

    @property
    def incomplete(self):
        if self.unreadable:
            return ("The original PNG samples could not be read for LSB inspection.",)
        return ()

    def report(self, answers):
        from .detection.evidence import reading_scores

        return {
            "layouts": list(self.layouts),
            "candidates": [
                {"layout": layout, "characters": len(text)}
                for layout, text in self.candidates
            ],
            "unreadable": self.unreadable,
            "scores": reading_scores(answers, ("ocr", READING)),
        }


def read_lsb(source, layouts):
    """Inspect original 8-bit RGB samples in the caller's declared layouts."""
    from PIL import Image

    from .images import is_8bit_rgb_png

    with BytesIO(source) if isinstance(source, bytes) else open(source, "rb") as file:
        if not is_8bit_rgb_png(file.read(26)):
            return None
        file.seek(0)
        try:
            with Image.open(file, formats=("PNG",)) as image:
                if image.n_frames != 1:
                    return None
                candidates = tuple(
                    (layout, text)
                    for layout in layouts
                    if (text := _text_candidate(image, layout))
                )
        except (OSError, SyntaxError, ValueError, Image.DecompressionBombError):
            return PngLsb(layouts, unreadable=True)
    return PngLsb(layouts, candidates)


def _text_candidate(image, layout):
    import numpy as np

    width, channels, bit_order, traversal = layout.split(",")
    depth = int(width[1:])
    bits_per_pixel = depth * len(channels)
    count = (PREVIEW_BYTES * 8 + bits_per_pixel - 1) // bits_per_pixel
    if traversal == "xy":
        pixels = islice(image.getdata(), count)
    else:
        at = image.load()
        positions = product(range(image.width), range(image.height))
        pixels = (at[x, y] for x, y in islice(positions, count))

    samples = np.asarray(list(pixels), dtype=np.uint8)[
        :, ["rgb".index(c) for c in channels]
    ]
    shifts = np.arange(depth - 1, -1, -1, dtype=np.uint8)
    bits = ((samples[..., None] >> shifts) & 1).ravel()
    byte_count = min(PREVIEW_BYTES, bits.size // 8)
    packed = np.packbits(
        bits[: byte_count * 8], bitorder="big" if bit_order == "lsb" else "little"
    )
    data = packed.tobytes().rstrip(b"\x00")
    if len(set(data)) <= 1:
        return ""
    match = TEXT_RUN.search(data)
    return match[0].decode("ascii").strip() if match else ""
