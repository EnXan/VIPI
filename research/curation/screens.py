"""Render generated interface screenshots with headless Chrome.

The attack screenshots in the catalog are HTML pages captured in a browser, so
the benign counterparts are made the same way (ADR 0051 rule 5). An item names
a ``template`` from ``screen_templates.py``; its ``text`` is the target text,
the only text the OCR reference covers. ``|`` in the text splits it into
fragments, which ``split_text`` places in separate elements (tiles, bubbles,
comments) and ``flowchart`` in connected steps. Screenshot-backed
``image_scaling`` embeds the target screenshot in a decoy screenshot with
Anamorpher. Items marked ``target_only_obfuscation`` keep rotation, mirroring,
blur and distortion on the target text instead of transforming the full page.
``unicode_homoglyphs`` swaps
letters before rendering; ``small_font`` sets the target text in
``SMALL_FONT_PX`` pixels; ``low_contrast`` fades it to
``LOW_CONTRAST_OPACITY``; ``base64`` shows the target text base64-encoded (the
encoded string is what the OCR reference covers); ``blur``, ``distorted_text``, ``mirrored_text`` and
``rotated_text`` are applied to the captured image by ``render.finish``.
Items with ``dark`` render in dark mode (``DARK_CSS``).

Chrome is found through ``VIPI_CHROME``, the macOS application path or
``google-chrome``/``chromium`` on ``PATH``.
"""

import base64
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from PIL import Image

from .render import (
    SEPARATOR,
    finish,
    reading_text,
    scaling_images,
    seeded,
    visible_text,
)
from .screen_templates import SIZES, TEMPLATES, theme

SUPPORTED = {
    "blur",
    "distorted_text",
    "mirrored_text",
    "rotated_text",
    "unicode_homoglyphs",
    "split_text",
    "flowchart",
    "small_font",
    "base64",
    "low_contrast",
    "image_scaling",
}
SMALL_FONT_PX = 9
LOW_CONTRAST_OPACITY = 0.3  # target text fades into whatever it sits on
# markers around the target text, swapped for a styled span after templating
START, END = "\x02", "\x03"
SPAN_STYLES = {
    "small_font": "font-size:%dpx" % SMALL_FONT_PX,
    "base64": "word-break:break-all",
    "low_contrast": "opacity:%.2f" % LOW_CONTRAST_OPACITY,
}
TARGET_SPAN_STYLES = {
    "blur": "filter:blur(1.2px)",
    "distorted_text": "display:inline-block;transform:skewX(-4deg);text-shadow:1px 0 currentColor",
    "mirrored_text": "display:inline-block;transform:scaleX(-1)",
    "rotated_text": "display:inline-block;transform:rotate(180deg)",
}
MAC_CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
CHROME_NAMES = ("google-chrome", "chromium", "chromium-browser")
CHROME_TIMEOUT_SECONDS = 120
BACKGROUND = (255, 255, 255)
# dark mode the way browser dark readers do it: invert lightness, keep hues,
# and turn photos back; one rule for every template keeps both labels alike
DARK_CSS = (
    "html{background:#fff;filter:invert(0.9) hue-rotate(180deg)}"
    "img,video{filter:invert(1) hue-rotate(180deg)}"
)


def chrome():
    candidates = [os.environ.get("VIPI_CHROME"), MAC_CHROME]
    candidates += [shutil.which(name) for name in CHROME_NAMES]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    raise ValueError("Chrome not found; set VIPI_CHROME to its executable")


def capture(html, size):
    """Screenshot an HTML page at a fixed window size."""
    with tempfile.TemporaryDirectory() as folder:
        page = Path(folder) / "page.html"
        shot = Path(folder) / "shot.png"
        page.write_text(html, encoding="utf-8")
        subprocess.run(
            [
                chrome(),
                "--headless=new",
                "--disable-gpu",
                "--hide-scrollbars",
                "--force-device-scale-factor=1",
                f"--window-size={size[0]},{size[1]}",
                f"--user-data-dir={folder}/profile",
                f"--screenshot={shot}",
                page.as_uri(),
            ],
            check=True,
            capture_output=True,
            timeout=CHROME_TIMEOUT_SECONDS,
        )
        with Image.open(shot) as image:
            return image.convert("RGB")


def visible(item):
    """The target text as it appears in the screenshot (``|`` kept)."""
    text, obfuscation = item["text"], item["obfuscation"]
    if "base64" in obfuscation:
        return base64.b64encode(reading_text(text).encode()).decode()
    return visible_text(text, obfuscation)


def fragments(item):
    parts = [part.strip() for part in visible(item).split(SEPARATOR) if part.strip()]
    styles = set(SPAN_STYLES)
    if item.get("target_only_obfuscation"):
        styles.update(TARGET_SPAN_STYLES)
    if not styles & set(item["obfuscation"]):
        return parts
    return [f"{START}{part}{END}" for part in parts]


def html(item):
    template = item["template"]
    if template not in TEMPLATES:
        raise ValueError(f"Unknown template {template!r}")
    obfuscation = item["obfuscation"]
    unknown = set(obfuscation) - SUPPORTED
    if unknown:
        raise ValueError(f"Cannot render obfuscation {sorted(unknown)} in a screenshot")
    if ("flowchart" in obfuscation) != (template in {"flow", "product_flow"}):
        raise ValueError("Use the flow template exactly for flowchart items")
    look = theme(seeded(item.get("theme_seed", item["text"])))
    split = "split_text" in obfuscation
    page = TEMPLATES[template](item, look, fragments(item), split)
    styles = dict(SPAN_STYLES)
    if item.get("target_only_obfuscation"):
        styles.update(TARGET_SPAN_STYLES)
    style = ";".join(styles[name] for name in styles if name in obfuscation)
    page = page.replace(START, f'<span style="{style}">').replace(END, "</span>")
    if item.get("dark"):
        page = page.replace("</style></head>", DARK_CSS + "</style></head>", 1)
    return page


def screen(item, position=0):
    image = capture(html(item), SIZES[item["template"]])
    if "image_scaling" in item["obfuscation"]:
        decoy_item = {
            **item,
            "text": item.get("decoy_text", ""),
            "theme_seed": item["text"],
            "obfuscation": [
                value for value in item["obfuscation"] if value != "image_scaling"
            ],
        }
        decoy = capture(html(decoy_item), SIZES[item["template"]])
        return scaling_images(decoy, image)
    obfuscation = item["obfuscation"]
    if item.get("target_only_obfuscation"):
        obfuscation = [name for name in obfuscation if name not in TARGET_SPAN_STYLES]
    return finish(image, obfuscation, position, BACKGROUND)
