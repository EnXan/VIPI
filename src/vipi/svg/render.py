"""Render a render-safe SVG copy to PNG with resvg.

The intrinsic size follows resvg (usvg) rules, which this module reproduces to
choose the scale before any raster is allocated: absolute `width`/`height`, a
percentage of the `viewBox`, a side derived from the `viewBox` aspect ratio,
or 100 user units.
"""

from dataclasses import dataclass
import io
import math
import re
import tempfile

from vipi.images import MAX_INPUT_PIXELS

# SVG has no native pixel resolution; diagrams use 10–12 px labels, which 1x
# leaves at the edge of local OCR. Browsers on HiDPI screens draw at 2x
# (ADR 0078).
RENDER_SCALE = 2.0
CSS_DPI = 96.0
DEFAULT_FONT_SIZE = 16.0
DEFAULT_SIDE = 100.0
UNITS = {
    "": 1.0,
    "px": 1.0,
    "in": CSS_DPI,
    "cm": CSS_DPI / 2.54,
    "mm": CSS_DPI / 25.4,
    "pt": CSS_DPI / 72,
    "pc": CSS_DPI / 6,
}
LENGTH = re.compile(
    r"^\s*([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)\s*(px|in|cm|mm|pt|pc|em|ex|%)?\s*$"
)


@dataclass(frozen=True)
class RenderedSvg:
    png: bytes
    intrinsic_size: tuple[int, int]
    size_source: str
    render_size: tuple[int, int]
    scale: float


def _length(value, font_size):
    """Return ("px", value) or ("%", fraction); None when absent or invalid."""
    match = LENGTH.match(value or "")
    if not match:
        return None
    number, unit = float(match.group(1)), match.group(2) or ""
    if number <= 0:
        raise ValueError("SVG has no usable size.")
    if unit == "%":
        return "%", number / 100
    if unit in {"em", "ex"}:
        return "px", number * font_size * (1 if unit == "em" else 0.5)
    return "px", number * UNITS[unit]


def _view_box(value):
    try:
        _, _, width, height = (
            float(part) for part in re.split(r"[\s,]+", value.strip())
        )
    except (AttributeError, ValueError):
        return None
    return (width, height) if width > 0 and height > 0 else None


def intrinsic_size(attributes):
    """Return `(width, height, size_source)` in pixels at 96 dpi."""
    font = _length(attributes.get("font-size"), DEFAULT_FONT_SIZE)
    font_size = font[1] if font and font[0] == "px" else DEFAULT_FONT_SIZE
    width = _length(attributes.get("width"), font_size)
    height = _length(attributes.get("height"), font_size)
    box = _view_box(attributes.get("viewBox"))
    bases = box or (DEFAULT_SIDE, DEFAULT_SIDE)

    def side(length, base):
        if length is None:
            return None
        kind, number = length
        return number if kind == "px" else base * number

    w, h = side(width, bases[0]), side(height, bases[1])
    explicit = (
        width is not None
        and height is not None
        and "%"
        not in {
            width[0],
            height[0],
        }
    )
    if box:
        if w is None and h is None:
            w, h = box
        elif w is None:
            w = h * box[0] / box[1]
        elif h is None:
            h = w * box[1] / box[0]
        source = "attributes" if explicit else "viewbox"
    else:
        w = DEFAULT_SIDE if w is None else w
        h = DEFAULT_SIDE if h is None else h
        source = "attributes" if explicit else "default"
    return math.floor(w + 0.5), math.floor(h + 0.5), source


def fitting_scale(width, height):
    """RENDER_SCALE, reduced until the rounded-up raster fits MAX_INPUT_PIXELS."""
    scale = min(RENDER_SCALE, math.sqrt(MAX_INPUT_PIXELS / (width * height)))
    while math.ceil(width * scale) * math.ceil(height * scale) > MAX_INPUT_PIXELS:
        scale *= 0.999
    return scale


def render_svg(document):
    """Render at RENDER_SCALE, reduced so the raster fits MAX_INPUT_PIXELS."""
    import resvg_py
    from PIL import Image

    width, height, source = intrinsic_size(document.size_attributes)
    if width < 1 or height < 1:
        raise ValueError("SVG has no usable size.")
    scale = fitting_scale(width, height)
    with tempfile.TemporaryDirectory(prefix="vipi-svg-") as empty:
        try:
            png = bytes(
                resvg_py.svg_to_bytes(
                    svg_string=document.render_markup,
                    background="#ffffff",
                    zoom=scale,
                    dpi=CSS_DPI,
                    resources_dir=empty,
                )
            )
        except Exception as error:
            raise ValueError(f"SVG could not be rendered: {error}") from None
    with Image.open(io.BytesIO(png)) as raster:
        size = raster.size
    if size[0] * size[1] > MAX_INPUT_PIXELS:
        raise ValueError(
            f"Rendered SVG exceeds {MAX_INPUT_PIXELS / 1_000_000:g} megapixels."
        )
    return RenderedSvg(png, (width, height), source, size, scale)
