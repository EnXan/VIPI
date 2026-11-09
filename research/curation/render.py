"""Render text images for generated catalog entries.

Two styles, used alike for benign and attack images (ADR 0051 rule 5):

- ``typographic`` reproduces the typographic source's look: 512x256 white
  canvas, Arial 19 px, 20 px margin, 26 px line pitch, low contrast in grey
  200. It pairs with the 45 typographic attack images.
- ``varied`` picks font, size, colours (no plain white), background pattern
  (solid, gradient, stripes, dots, grid, checker, noise), canvas and
  alignment from a fixed palette, seeded by the text, so one spec renders the
  same on every run.

Obfuscations: ``low_contrast``, ``italic_font``, ``small_font``, ``blur``,
``distorted_text``, ``rotated_text``, ``mirrored_text`` (applied to either
style), ``unicode_homoglyphs`` (Latin letters swapped for Cyrillic
lookalikes), ``split_text`` (the text spread over numbered panels, read in
panel order), ``flowchart`` (the text split into connected step boxes) and
``image_scaling`` (text that 4:1 nearest-neighbour downscaling reveals, made
with Trail of Bits Anamorpher's generator from a local checkout pinned at
``ANAMORPHER_COMMIT``; other resampling methods do not reveal it).
"""

import hashlib
import importlib.util
import math
import os
from pathlib import Path
import random

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

SIZE = (512, 256)
MARGIN = 20
TEXT_TOP = 17
LINE_PITCH = 26
FONT_SIZE = 19
SMALL_FONT_SIZE = 11
SMALL_LINE_PITCH = 15
LOW_CONTRAST_GREY = 200
LOW_CONTRAST_MIX = 0.22
BLUR_RADIUS = 1.6
WAVE_AMPLITUDE = 3
WAVE_PERIOD = 36
ROTATIONS = (90, 180, -90)
HOMOGLYPH_SHARE = 0.5
HOMOGLYPHS = {
    "a": "\u0430", "c": "\u0441", "e": "\u0435", "i": "\u0456", "o": "\u043e",
    "p": "\u0440", "x": "\u0445", "y": "\u0443", "A": "\u0410", "B": "\u0412",
    "C": "\u0421", "E": "\u0415", "H": "\u041d", "K": "\u041a", "M": "\u041c",
    "O": "\u041e", "P": "\u0420", "T": "\u0422", "X": "\u0425",
}  # fmt: skip
SPLIT_PANELS = 3
SEPARATOR = "|"
FLOW_STEPS = 3
SCALING_FACTOR = 4
# Anamorpher settings matched to the catalog's anamorpher_0000/0001 images:
# 3200x3200 grey decoy, 800x800 target, teal text after downscaling.
ANAMORPHER = Path(
    os.environ.get(
        "VIPI_ANAMORPHER",
        Path(__file__).resolve().parents[2] / ".local-assets/anamorpher",
    )
)
ANAMORPHER_COMMIT = "6aa9877ed64d0d1b1bf6d8b86d754ab5098c155b"
SCALING_TARGET = (800, 800)
SCALING_DECOY = (58, 59, 59)
SCALING_TARGET_BACKGROUND = (49, 60, 60)
SCALING_TEXT = (0, 60, 60)
SCALING_FONT_SIZE = 28
SCALING_MARGIN = 60

SUPPLEMENTAL = Path("/System/Library/Fonts/Supplemental")
WINDOWS_FONTS = Path("C:/Windows/Fonts")
LINUX_FONTS = Path("/usr/share/fonts")
# Each family: (regular, italic) file names on macOS, Windows and Linux. macOS
# comes first so existing generated images reproduce byte for byte; Windows has
# the same faces; on Linux the metric-compatible Liberation fonts and DejaVu
# stand in (``apt install fonts-liberation fonts-dejavu``).
FAMILIES = {
    "Arial": (
        ("Arial.ttf", "Arial Italic.ttf"),
        ("arial.ttf", "ariali.ttf"),
        ("LiberationSans-Regular.ttf", "LiberationSans-Italic.ttf"),
    ),
    "Times New Roman": (
        ("Times New Roman.ttf", "Times New Roman Italic.ttf"),
        ("times.ttf", "timesi.ttf"),
        ("LiberationSerif-Regular.ttf", "LiberationSerif-Italic.ttf"),
    ),
    "Georgia": (
        ("Georgia.ttf", "Georgia Italic.ttf"),
        ("georgia.ttf", "georgiai.ttf"),
        ("DejaVuSerif.ttf", "DejaVuSerif-Italic.ttf"),
    ),
    "Courier New": (
        ("Courier New.ttf", "Courier New Italic.ttf"),
        ("cour.ttf", "couri.ttf"),
        ("LiberationMono-Regular.ttf", "LiberationMono-Italic.ttf"),
    ),
    "Verdana": (
        ("Verdana.ttf", "Verdana Italic.ttf"),
        ("verdana.ttf", "verdanai.ttf"),
        ("DejaVuSans.ttf", "DejaVuSans-Oblique.ttf"),
    ),
    "Trebuchet MS": (
        ("Trebuchet MS.ttf", "Trebuchet MS Italic.ttf"),
        ("trebuc.ttf", "trebucit.ttf"),
        ("DejaVuSansCondensed.ttf", "DejaVuSansCondensed-Oblique.ttf"),
    ),
    "Tahoma": (("Tahoma.ttf", None), ("tahoma.ttf", None), (None, None)),
    "Comic Sans MS": (("Comic Sans MS.ttf", None), ("comic.ttf", None), (None, None)),
}
# Always available, so rendering works without any system font (SIL OFL).
BUNDLED = Path(__file__).resolve().parents[1] / "workbench/static/fonts/Geist.ttf"
CANVASES = ((512, 256), (640, 360), (480, 480), (800, 300), (600, 400))
COLOURS = (  # background, text; no plain white, the typographic style has it
    ((250, 246, 236), (60, 40, 25)),
    ((236, 239, 243), (25, 45, 90)),
    ((40, 44, 52), (235, 235, 235)),
    ((255, 249, 196), (30, 30, 30)),
    ((225, 240, 250), (10, 40, 80)),
    ((18, 32, 66), (255, 214, 102)),
    ((176, 32, 45), (255, 255, 255)),
    ((22, 101, 72), (240, 250, 240)),
    ((92, 45, 145), (255, 240, 255)),
    ((255, 140, 50), (35, 20, 10)),
    ((0, 128, 128), (255, 255, 255)),
    ((252, 220, 230), (110, 20, 60)),
    ((210, 235, 200), (30, 60, 20)),
    ((20, 20, 20), (120, 255, 140)),
    ((70, 90, 110), (255, 255, 255)),
    ((245, 200, 70), (40, 30, 0)),
)
PATTERNS = ("solid", "gradient", "stripes", "dots", "grid", "checker", "noise")
PATTERN_SHIFT = 22  # how far pattern colours move from the background
SUPPORTED = {
    "low_contrast", "italic_font", "small_font", "blur", "distorted_text",
    "rotated_text", "mirrored_text", "unicode_homoglyphs", "split_text",
    "flowchart", "image_scaling",
}  # fmt: skip
STYLES = ("typographic", "varied")


def font_paths(family, italic):
    """Candidate files for one family and style, macOS first."""
    mac, windows, linux = (names[1 if italic else 0] for names in FAMILIES[family])
    paths = [SUPPLEMENTAL / mac] if mac else []
    if windows:
        paths.append(WINDOWS_FONTS / windows)
    if linux and LINUX_FONTS.is_dir():
        paths += sorted(LINUX_FONTS.rglob(linux))
    return paths


def font(family, italic, size):
    for path in font_paths(family, italic):
        if path.is_file():
            return ImageFont.truetype(str(path), size)
    if family == "Arial" and not italic:
        return ImageFont.truetype(str(BUNDLED), size)
    raise OSError(f"Font {family} {'italic' if italic else 'regular'} not found")


def available(italic):
    families = []
    for family in FAMILIES:
        try:
            font(family, italic, FONT_SIZE)
        except OSError:
            continue
        families.append(family)
    return families


def seeded(text):
    return random.Random(hashlib.sha256(text.encode()).digest())


def homoglyphs(text):
    """Swap about half of the swappable Latin letters, the same way every run."""
    chooser = seeded(text)
    return "".join(
        HOMOGLYPHS[c] if c in HOMOGLYPHS and chooser.random() < HOMOGLYPH_SHARE else c
        for c in text
    )


def reading_text(text):
    """The text as a reader sees it, without fragment separators."""
    return " ".join(text.replace(SEPARATOR, " ").split())


def visible_text(text, obfuscation):
    """The characters rendered into the image."""
    shown = reading_text(text) if SEPARATOR not in text else text
    return homoglyphs(shown) if "unicode_homoglyphs" in obfuscation else shown


def wrap(text, face, width):
    lines, line = [], ""
    for word in text.split():
        candidate = f"{line} {word}".strip()
        if line and face.getlength(candidate) > width:
            lines.append(line)
            line = word
        else:
            line = candidate
    return [*lines, line] if line else lines


def chunks(text, count):
    """Fragments for panels or steps: split at ``|`` if the text has any,
    otherwise into ``count`` parts of similar word count."""
    if SEPARATOR in text:
        return [part.strip() for part in text.split(SEPARATOR) if part.strip()]
    words = text.split()
    size = math.ceil(len(words) / count)
    return [" ".join(words[i : i + size]) for i in range(0, len(words), size)]


def look(text, obfuscation, style):
    """Canvas size, colours, font, pitch, margin and alignment for a style."""
    italic = "italic_font" in obfuscation
    small = "small_font" in obfuscation
    if style == "typographic":
        size = SMALL_FONT_SIZE if small else FONT_SIZE
        grey = LOW_CONTRAST_GREY if "low_contrast" in obfuscation else 0
        return {
            "canvas": SIZE, "background": (255, 255, 255), "ink": (grey,) * 3,
            "face": font("Arial", italic, size),
            "pitch": SMALL_LINE_PITCH if small else LINE_PITCH,
            "margin": MARGIN, "top": TEXT_TOP, "centre": False,
        }  # fmt: skip
    chooser = seeded(text)
    background, ink = chooser.choice(COLOURS)
    pattern = chooser.choice(PATTERNS)
    if "low_contrast" in obfuscation:
        ink = tuple(
            round(b + (i - b) * LOW_CONTRAST_MIX) for b, i in zip(background, ink)
        )
    size = chooser.randint(11, 13) if small else chooser.randint(17, 30)
    canvas = chooser.choice(CANVASES)
    return {
        "canvas": canvas, "background": background, "ink": ink,
        "pattern": pattern, "seed": chooser.random(),
        "face": font(chooser.choice(available(italic)), italic, size),
        "pitch": round(size * chooser.uniform(1.25, 1.6)),
        "margin": chooser.randint(16, 48), "top": None,
        "centre": chooser.random() < 0.4,
    }  # fmt: skip


def shifted(colour, amount):
    """Move a colour towards black or white, whichever leaves more room."""
    direction = -1 if sum(colour) > 382 else 1
    return tuple(max(0, min(255, c + direction * amount)) for c in colour)


def canvas(style, size):
    """Background of ``size`` in the style's colour and pattern."""
    base = style["background"]
    accent = shifted(base, PATTERN_SHIFT)
    pattern = style.get("pattern", "solid")
    image = Image.new("RGB", size, base)
    draw = ImageDraw.Draw(image)
    width, height = size
    step = 18 + round(style.get("seed", 0) * 22)
    if pattern == "gradient":
        far = shifted(base, PATTERN_SHIFT * 3)
        for y in range(height):
            mix = y / max(height - 1, 1)
            draw.line(
                (0, y, width, y),
                fill=tuple(round(a + (b - a) * mix) for a, b in zip(base, far)),
            )
    elif pattern == "stripes":
        for x in range(-height, width, step):
            draw.line((x, height, x + height, 0), fill=accent, width=step // 3)
    elif pattern == "dots":
        for y in range(step // 2, height, step):
            for x in range(step // 2, width, step):
                draw.ellipse((x - 2, y - 2, x + 2, y + 2), fill=accent)
    elif pattern == "grid":
        for x in range(0, width, step):
            draw.line((x, 0, x, height), fill=accent)
        for y in range(0, height, step):
            draw.line((0, y, width, y), fill=accent)
    elif pattern == "checker":
        for y in range(0, height, step):
            for x in range((y // step) % 2 * step, width, 2 * step):
                draw.rectangle((x, y, x + step - 1, y + step - 1), fill=accent)
    elif pattern == "noise":
        noise = random.Random(style.get("seed", 0))
        pixels = image.load()
        for y in range(height):
            for x in range(width):
                shade = noise.randint(-PATTERN_SHIFT // 2, PATTERN_SHIFT // 2)
                pixels[x, y] = tuple(max(0, min(255, c + shade)) for c in base)
    return image


def draw_block(draw, lines, style, box):
    """Draw wrapped lines inside ``box`` (left, top, right, bottom)."""
    left, top, right, bottom = box
    height = style["pitch"] * len(lines)
    if height > bottom - top:
        raise ValueError("Text does not fit the canvas")
    y = top if style["top"] is not None else top + (bottom - top - height) // 2
    for number, line in enumerate(lines):
        x = left
        if style["centre"]:
            x = left + (right - left - style["face"].getlength(line)) / 2
        draw.text(
            (x, y + number * style["pitch"]),
            line,
            font=style["face"],
            fill=style["ink"],
        )


def plain(text, style):
    image = canvas(style, style["canvas"])
    width, height = style["canvas"]
    margin = style["margin"]
    top = style["top"] if style["top"] is not None else margin
    lines = wrap(text, style["face"], width - 2 * margin)
    draw_block(
        ImageDraw.Draw(image),
        lines,
        style,
        (margin, top, width - margin, height - margin),
    )
    return image


def split_panels(text, style):
    """One panel per text fragment, numbered below in reading order."""
    parts = chunks(text, SPLIT_PANELS)
    panel = (300, 220)
    image = canvas(style, (panel[0] * len(parts), panel[1] + 50))
    draw = ImageDraw.Draw(image)
    for number, part in enumerate(parts):
        left = number * panel[0]
        lines = wrap(part, style["face"], panel[0] - 40)
        draw_block(
            draw,
            lines,
            {**style, "top": None, "centre": True},
            (left + 20, 20, left + panel[0] - 20, panel[1]),
        )
        label = str(number + 1)
        draw.text(
            (left + panel[0] / 2 - style["face"].getlength(label) / 2, panel[1] + 12),
            label,
            font=style["face"],
            fill=style["ink"],
        )
    return image


def flowchart(text, style):
    """Step boxes top to bottom, joined by arrows."""
    parts = chunks(text, FLOW_STEPS)
    face, pitch = style["face"], style["pitch"]
    width, box_width, gap = 560, 440, 44
    wrapped = [
        wrap(f"Step {n + 1}: {part}", face, box_width - 32)
        for n, part in enumerate(parts)
    ]
    heights = [pitch * len(lines) + 28 for lines in wrapped]
    image = canvas(style, (width, sum(heights) + gap * (len(parts) - 1) + 60))
    draw = ImageDraw.Draw(image)
    left, y = (width - box_width) // 2, 30
    for number, (lines, height) in enumerate(zip(wrapped, heights)):
        draw.rounded_rectangle(
            (left, y, left + box_width, y + height),
            radius=12,
            fill=style["background"],
            outline=style["ink"],
            width=2,
        )
        draw_block(
            draw,
            lines,
            {**style, "top": 0, "centre": True},
            (left + 16, y + 14, left + box_width - 16, y + height),
        )
        y += height
        if number < len(parts) - 1:
            middle = width // 2
            draw.line((middle, y + 4, middle, y + gap - 8), fill=style["ink"], width=2)
            draw.polygon(
                [
                    (middle - 7, y + gap - 14),
                    (middle + 7, y + gap - 14),
                    (middle, y + gap - 4),
                ],
                fill=style["ink"],
            )
            y += gap
    return image


def anamorpher():
    """Trail of Bits Anamorpher's nearest-neighbour generator (numpy only)."""
    path = ANAMORPHER / "backend" / "adversarial_generators" / "nearest_gen_payload.py"
    if not path.is_file():
        raise ValueError(
            f"Anamorpher not found at {ANAMORPHER}; clone "
            f"https://github.com/trailofbits/anamorpher there at {ANAMORPHER_COMMIT} "
            "or set VIPI_ANAMORPHER"
        )
    spec = importlib.util.spec_from_file_location("anamorpher_nearest", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def scaling_images(decoy, target):
    """Embed an 800 px target in a 3200 px decoy using Anamorpher."""
    target = ImageOps.pad(target.convert("RGB"), SCALING_TARGET, color=(244, 245, 247))
    decoy = ImageOps.pad(
        decoy.convert("RGB"),
        tuple(SCALING_FACTOR * side for side in SCALING_TARGET),
        color=(244, 245, 247),
    )
    generator = anamorpher()
    hidden = generator.embed_nn(
        generator.srgb2lin(np.asarray(decoy, dtype=np.float32)),
        generator.srgb2lin(np.asarray(target, dtype=np.float32)),
        lam=0.25,
        eps=0.0,
        gamma_target=1.0,
        offset=SCALING_FACTOR // 2,
    )
    return Image.fromarray(generator.lin2srgb(hidden).round().astype(np.uint8))


def scaling(text, obfuscation):
    """Text that only 4:1 nearest-neighbour downscaling reveals."""
    target = Image.new("RGB", SCALING_TARGET, SCALING_TARGET_BACKGROUND)
    draw = ImageDraw.Draw(target)
    face = font("Arial", False, SCALING_FONT_SIZE)
    lines = wrap(text, face, SCALING_TARGET[0] - 2 * SCALING_MARGIN)
    pitch = round(SCALING_FONT_SIZE * 1.3)
    y = (SCALING_TARGET[1] - pitch * len(lines)) // 2
    for line in lines:
        x = (SCALING_TARGET[0] - face.getlength(line)) / 2
        draw.text((x, y), line, font=face, fill=SCALING_TEXT)
        y += pitch
    decoy = Image.new(
        "RGB", tuple(SCALING_FACTOR * side for side in SCALING_TARGET), SCALING_DECOY
    )
    return scaling_images(decoy, target)


def distort_rows(image, background):
    result = Image.new(image.mode, image.size, background)
    for row in range(image.height):
        shift = round(WAVE_AMPLITUDE * math.sin(2 * math.pi * row / WAVE_PERIOD))
        result.paste(image.crop((0, row, image.width, row + 1)), (shift, row))
    return result


def finish(image, obfuscation, position, background):
    if "distorted_text" in obfuscation:
        image = distort_rows(image, background)
    if "blur" in obfuscation:
        image = image.filter(ImageFilter.GaussianBlur(BLUR_RADIUS))
    if "mirrored_text" in obfuscation:
        image = ImageOps.mirror(image)
    if "rotated_text" in obfuscation:
        angle = ROTATIONS[position % len(ROTATIONS)]
        image = image.rotate(angle, expand=True, fillcolor=background)
    return image


def render(text, obfuscation, position=0, style="typographic"):
    unknown = set(obfuscation) - SUPPORTED
    if unknown:
        raise ValueError(f"Cannot render obfuscation {sorted(unknown)}")
    if style not in STYLES:
        raise ValueError(f"Choose style {', '.join(STYLES)}")
    shown = visible_text(text, obfuscation)
    if "image_scaling" in obfuscation:
        return scaling(shown, obfuscation)
    chosen = look(text, obfuscation, style)
    if "split_text" in obfuscation:
        image = split_panels(shown, chosen)
    elif "flowchart" in obfuscation:
        image = flowchart(shown, chosen)
    else:
        try:
            image = plain(reading_text(shown), chosen)
        except ValueError as error:
            raise ValueError(f"{error}: {text[:40]!r}") from error
    return finish(image, obfuscation, position, chosen["background"])


OVERLAY_ALPHA = 64  # of 255: faint white text, like the transparency attacks
OVERLAY_FONT_SHARE = 1 / 14  # font size as a share of the photo width
OVERLAY_WIDTH_SHARE = 0.6
OVERLAY_LINE_SPACING = 1.15


def overlay(photo, text):
    """Large, faint white text over a photo (``high_transparency``)."""
    base = photo.convert("RGBA")
    size = round(base.width * OVERLAY_FONT_SHARE)
    face = font("Arial", False, size)
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    x, y = round(base.width * 0.18), round(base.height * 0.14)
    for line in wrap(reading_text(text), face, base.width * OVERLAY_WIDTH_SHARE):
        draw.text((x, y), line, font=face, fill=(255, 255, 255, OVERLAY_ALPHA))
        y += round(size * OVERLAY_LINE_SPACING)
    return Image.alpha_composite(base, layer).convert("RGB")


def overlay_regions(photo, text, regions, obfuscation=()):
    """Overlay split photo text at normalized, independently placed regions."""
    parts = [part.strip() for part in text.split(SEPARATOR) if part.strip()]
    if len(parts) != len(regions):
        raise ValueError("Each text fragment needs one text region")
    base = photo.convert("RGBA")
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    for part, region in zip(parts, regions):
        x = round(region["x"] * base.width)
        y = round(region["y"] * base.height)
        width = round(region["width"] * base.width)
        height = round(region["height"] * base.height)
        size = round(region.get("font_size", base.width * 0.026))
        face = font(region.get("font", "Georgia"), region.get("italic", True), size)
        fill = tuple(region.get("fill", (39, 47, 57, 178)))
        pitch = round(size * 1.25)
        lines = wrap(part, face, width)
        if pitch * len(lines) > height:
            raise ValueError("Text does not fit its configured photo region")
        for row, line in enumerate(lines):
            draw.text((x, y + row * pitch), line, font=face, fill=fill)
    if "distorted_text" in obfuscation:
        layer = distort_rows(layer, (0, 0, 0, 0))
    return Image.alpha_composite(base, layer).convert("RGB")
