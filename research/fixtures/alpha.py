"""Text hidden in transparent pixels (`vipi.transparency`, ADR 0085).

VIPI composites onto white for OCR and also scans an image with transparent
pixels on black and with alpha dropped. For each text pixel the writer solves
the compositing equations so the white view keeps the composition:

- `black`: shows on black. With white-view colour W and wanted black-view
  colour B, alpha a = 1 - (W - B) / 255 and colour C = B / a. B must not be
  brighter than W in any channel.
- `rgb`: shows when alpha is dropped. The pixel becomes fully transparent with
  colour C = the text colour; it is white on white and black on black.
"""

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .scaling import FONT

MODES = {"black": "Shows on a black background", "rgb": "Shows when alpha is dropped"}


def validate(layer):
    if layer.get("mode") not in MODES:
        raise ValueError(f"Choose one of: {', '.join(MODES)}.")
    text = layer.get("text")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("A transparency layer needs text.")
    clean = {"mode": layer["mode"], "text": text}
    for key in ("size", "x", "y"):
        if not isinstance(layer.get(key), (int, float)):
            raise ValueError(f"A transparency layer needs a numeric {key}.")
        clean[key] = layer[key]
    color = layer.get("color", "#000000")
    if not isinstance(color, str) or len(color) != 7 or color[0] != "#":
        raise ValueError("Colours are #rrggbb.")
    clean["color"] = np.array(
        [int(color[i : i + 2], 16) for i in (1, 3, 5)], dtype=float
    )
    return clean


def mask(size, layer):
    """Boolean mask of the layer's text pixels."""
    canvas = Image.new("L", size, 0)
    font = ImageFont.truetype(str(FONT), max(1, round(layer["size"])))
    ImageDraw.Draw(canvas).multiline_text(
        (layer["x"], layer["y"]),
        layer["text"],
        font=font,
        fill=255,
        anchor="mm",
        align="center",
    )
    return np.asarray(canvas) > 127


def embed(image, layer):
    """Return the RGBA image with the layer written and the text mask."""
    rgba = np.array(image.convert("RGBA"), dtype=float)
    where = mask(image.size, layer)
    white = rgba[..., :3][where]
    if layer["mode"] == "black":
        # One alpha per pixel: the channel that must darken most decides it;
        # the colour then keeps the white view at W in every channel.
        black = np.minimum(layer["color"], white)
        alpha = 1 - (white - black).max(axis=1, keepdims=True) / 255
        safe = np.where(alpha > 0, alpha, 1)
        colour = np.where(alpha > 0, (white - (1 - alpha) * 255) / safe, white)
    else:
        alpha = np.zeros((len(white), 1))
        colour = np.broadcast_to(layer["color"], white.shape)
    rgba[..., :3][where] = np.clip(np.round(colour), 0, 255)
    rgba[..., 3][where] = np.round(alpha[:, 0] * 255)
    return Image.fromarray(rgba.astype(np.uint8)), where


def check(views, layer, where):
    """Text pixels that differ from the white view in the layer's view."""
    from io import BytesIO

    from vipi.transparency import VIEWS

    rasters = {}
    for view in views.views if views else ():
        source = views.view(view.same_as) if view.same_as else view
        with Image.open(BytesIO(source.png)) as image:
            rasters[view.name] = np.asarray(image.convert("RGB")).astype(int)
    if set(rasters) != set(VIEWS):
        return 0, int(where.sum())
    shown = np.abs(rasters[layer["mode"]] - rasters["white"]).max(axis=2)[where] > 0
    return int(shown.sum()), int(where.sum())
