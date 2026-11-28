"""Compose a recipe's visible layers with Pillow, as the editor's canvas does.

The editor draws the background, removed areas, text and code layers in the
browser and sends the result to `encode`. Without a browser (the MCP server)
this module draws the same recipe: same positions, rotation, skew, mirror,
opacity, blur and line height (1.25), with the bundled Geist fonts or an
installed system font by name. Glyph shapes differ slightly from the browser's
font renderer; the fixture records the written file, so read-back and the
expected text stay exact.
"""

import base64
from io import BytesIO
import math
from pathlib import Path
import re

from PIL import Image, ImageDraw, ImageFilter, ImageFont, UnidentifiedImageError

from research.fixtures import codes, heal
from research.fixtures.recipe import LINE_HEIGHT, transform

FONTS = Path(__file__).resolve().parents[1] / "workbench" / "static" / "fonts"
BUNDLED = {"geist": FONTS / "Geist.ttf", "geist mono": FONTS / "GeistMono.ttf"}
SYSTEM_FONT_DIRS = (
    Path("/System/Library/Fonts"),
    Path("/System/Library/Fonts/Supplemental"),
    Path("/Library/Fonts"),
    Path.home() / "Library" / "Fonts",
    Path("/usr/share/fonts"),
    Path.home() / ".fonts",
    Path("C:/Windows/Fonts"),
)
ITALIC_SLANT = 0.2  # browsers slant a font without an italic face by about this
# Characters browsers draw as nothing (zero-width and Unicode tag characters).
INVISIBLE = re.compile("[\u200b-\u200f\u2060-\u2064\ufeff\U000e0000-\U000e007f]")


def font_file(name):
    """The font file for a family name, or None when it is not installed."""
    key = name.strip().casefold()
    if key in BUNDLED:
        return BUNDLED[key]
    wanted = key.replace(" ", "")
    for folder in SYSTEM_FONT_DIRS:
        if not folder.is_dir():
            continue
        for path in folder.rglob("*"):
            if path.suffix.lower() in {".ttf", ".otf", ".ttc"}:
                if path.stem.casefold().replace(" ", "") == wanted:
                    return path
    return None


def _image(source):
    """A background image from a data URL or a file path."""
    if source.startswith("data:"):
        data = base64.b64decode(source.split(",", 1)[1])
    else:
        data = Path(source).read_bytes()
    try:
        with Image.open(BytesIO(data)) as image:
            return image.convert("RGB")
    except (UnidentifiedImageError, OSError):
        raise ValueError("The background image could not be decoded.") from None


def _png(image):
    buffer = BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


def _rgb(hex_colour):
    return tuple(int(hex_colour[index : index + 2], 16) for index in (1, 3, 5))


def _mask_of(marks, size):
    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    for mark in marks:
        if "polygon" in mark:  # a text line, padded like the editor's mask
            points = [tuple(point) for point in mark["polygon"]]
            pad = float(mark.get("pad", 3))
            draw.polygon(points, fill=255)
            draw.line(
                [*points, points[0]], fill=255, width=round(2 * pad), joint="curve"
            )
            continue
        radius = float(mark["size"]) / 2
        points = [tuple(point) for point in mark["points"]]
        if len(points) > 1:
            draw.line(points, fill=255, width=round(2 * radius), joint="curve")
        for x, y in points:  # round caps
            draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=255)
    return mask


def _draw_text(base, layer, notes):
    shown = INVISIBLE.sub("", transform(layer["text"], layer["encoding"]))
    lines = shown.split("\n")
    path = font_file(layer["font"])
    if path is None:
        notes.append(f"Font {layer['font']!r} is not installed; drew it in Geist.")
        path = BUNDLED["geist"]
    size = float(layer["size"])
    font = ImageFont.truetype(str(path), max(1, round(size)))
    try:
        font.set_variation_by_axes([600 if layer["bold"] else 400])
    except (OSError, AttributeError):  # a static font has no weight axis
        pass
    pitch = size * LINE_HEIGHT
    width = max([1.0, *(font.getlength(line) for line in lines)])
    margin = size + 3 * float(layer["blur"])
    block = Image.new(
        "L",
        (math.ceil(width + 2 * margin), math.ceil(len(lines) * pitch + 2 * margin)),
        0,
    )
    centre = (block.width / 2, block.height / 2)
    draw = ImageDraw.Draw(block)
    for index, line in enumerate(lines):
        offset = (index - (len(lines) - 1) / 2) * pitch
        draw.text(
            (centre[0], centre[1] + offset), line, font=font, fill=255, anchor="mm"
        )
    # Forward map, as on the canvas: translate · rotate · skew · mirror · italic.
    angle = math.radians(float(layer["rotation"]))
    cos, sin = math.cos(angle), math.sin(angle)
    shear = math.tan(math.radians(float(layer["skew"])))
    mirror = -1.0 if layer["mirror"] else 1.0
    slant = -ITALIC_SLANT if layer["italic"] else 0.0
    # K·M·I = [[mirror, mirror*slant + shear], [0, 1]]; then R.
    a, b = mirror, mirror * slant + shear
    m11, m12 = cos * a, cos * b - sin
    m21, m22 = sin * a, sin * b + cos
    det = m11 * m22 - m12 * m21
    i11, i12, i21, i22 = m22 / det, -m12 / det, -m21 / det, m11 / det
    tx, ty = float(layer["x"]), float(layer["y"])
    coverage = block.transform(
        base.size,
        Image.Transform.AFFINE,
        (
            i11,
            i12,
            -(i11 * tx + i12 * ty) + centre[0],
            i21,
            i22,
            -(i21 * tx + i22 * ty) + centre[1],
        ),
        resample=Image.Resampling.BICUBIC,
    )
    if float(layer["blur"]) > 0:
        coverage = coverage.filter(ImageFilter.GaussianBlur(float(layer["blur"])))
    alpha = coverage.point(lambda value: round(value * float(layer["opacity"])))
    return Image.composite(
        Image.new("RGB", base.size, _rgb(layer["color"])), base, alpha
    )


def _draw_code(base, layer):
    data, _ = codes.module_png(layer["format"], layer["text"])
    with Image.open(BytesIO(data)) as modules:
        grey = modules.convert("L")
    dark, light = _rgb(layer["color"]), _rgb(layer["paper"])
    coloured = Image.merge(
        "RGB",
        [
            grey.point(lambda value, d=d, p=p: d if value < 128 else p)
            for d, p in zip(dark, light, strict=True)
        ],
    )
    module = int(layer["module"])
    coloured = coloured.resize(
        (coloured.width * module, coloured.height * module), Image.Resampling.NEAREST
    )
    corner = (
        round(float(layer["x"]) - coloured.width / 2),
        round(float(layer["y"]) - coloured.height / 2),
    )
    opacity = Image.new("L", coloured.size, round(255 * float(layer["opacity"])))
    base.paste(coloured, corner, opacity)
    return base


def compose(recipe):
    """PNG bytes of the visible layers and notes on what differs from the request."""
    canvas = recipe["canvas"]
    size = (int(canvas["width"]), int(canvas["height"]))
    base = Image.new("RGB", size, _rgb(canvas["background"]))
    if canvas.get("background_image"):
        image = _image(canvas["background_image"])
        base.paste(image.resize(size, Image.Resampling.BILINEAR))
    notes = []
    removed = [
        mark
        for layer in recipe["layers"]
        if layer["kind"] == "heal" and layer.get("visible", True) is not False
        for mark in layer["strokes"]
    ]
    if removed:
        healed = heal.heal(_png(base), _png(_mask_of(removed, size)))
        with Image.open(BytesIO(healed)) as filled:
            base = filled.convert("RGB")
    for layer in recipe["layers"]:
        if layer.get("visible", True) is False:
            continue
        if layer["kind"] == "text" and layer["text"].strip():
            base = _draw_text(base, layer, notes)
        elif layer["kind"] == "code":
            base = _draw_code(base, layer)
    return _png(base), notes
