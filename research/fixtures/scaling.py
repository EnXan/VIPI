"""Downscaled views and image-scaling attacks (obfuscation `image_scaling`).

A model pipeline often shrinks an image before the model sees it. Resizers
that sample few source pixels (nearest neighbour, bilinear without
antialiasing) only look at some pixels, so text written into exactly those
pixels appears after downscaling and is barely visible at full size. Pillow's
bilinear, bicubic and Lanczos filters and OpenCV's area filter average every
pixel and are the usual defence; VIPI itself scans the full-size image and
shrinks with Lanczos only for cloud image checks.

The sampled pixels are taken from the resizer itself (nearest) or from the
OpenCV bilinear coordinate mapping, which the tests compare with OpenCV.
"""

from io import BytesIO
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

FONT = Path(__file__).resolve().parents[1] / "workbench/static/fonts/Geist.ttf"
PILLOW = {
    "pillow_nearest": Image.Resampling.NEAREST,
    "pillow_bilinear": Image.Resampling.BILINEAR,
    "pillow_bicubic": Image.Resampling.BICUBIC,
    "pillow_lanczos": Image.Resampling.LANCZOS,
}
TITLES = {
    "pillow_nearest": "Pillow nearest",
    "pillow_bilinear": "Pillow bilinear",
    "pillow_bicubic": "Pillow bicubic",
    "pillow_lanczos": "Pillow Lanczos (VIPI cloud check)",
    "opencv_nearest": "OpenCV nearest",
    "opencv_bilinear": "OpenCV bilinear (no antialiasing)",
    "opencv_area": "OpenCV area",
}
# Methods an attack layer can target: each output pixel reads a few inputs.
ATTACKABLE = ("pillow_nearest", "opencv_nearest", "opencv_bilinear")


def _cv2():
    try:
        import cv2
    except ImportError:
        return None
    return cv2


def methods():
    """Available methods; OpenCV ones need the `ocr` extra."""
    available = [name for name in TITLES if name in PILLOW or _cv2()]
    return [
        {"id": name, "title": TITLES[name], "attackable": name in ATTACKABLE}
        for name in available
    ]


def target_size(size, width):
    """The downscaled size for a target width, keeping the aspect ratio."""
    width = int(width)
    if not 1 <= width < size[0]:
        raise ValueError(f"Choose a target width from 1 to {size[0] - 1} px.")
    # Half up, as JavaScript's Math.round in the editor (round() would round half to even).
    return width, max(1, int(size[1] * width / size[0] + 0.5))


def downscale(image, method, size):
    if method in PILLOW:
        return image.resize(size, PILLOW[method])
    cv2 = _cv2()
    if cv2 is None or method not in TITLES:
        raise ValueError(f"Unknown or unavailable scaling method: {method!r}.")
    flag = {
        "opencv_nearest": cv2.INTER_NEAREST,
        "opencv_bilinear": cv2.INTER_LINEAR,
        "opencv_area": cv2.INTER_AREA,
    }[method]
    return Image.fromarray(cv2.resize(np.asarray(image), size, interpolation=flag))


def preview(data, method, width):
    """PNG of the encoded file as the chosen resizer delivers it."""
    with Image.open(BytesIO(data)) as image:
        rgb = image.convert("RGB")
    buffer = BytesIO()
    downscale(rgb, method, target_size(rgb.size, width)).save(buffer, "PNG")
    return buffer.getvalue()


def sampled(method, source, target):
    """For each output index, the input indices the resizer reads."""
    if method == "opencv_bilinear":
        positions = (np.arange(target) + 0.5) * source / target - 0.5
        low = np.floor(np.clip(positions, 0, None)).astype(int)
        return [sorted({int(i), int(min(i + 1, source - 1))}) for i in low]
    # Nearest: resize an index ramp and read which index each output got.
    ramp = np.arange(source, dtype=np.int32)[None, :].repeat(2, axis=0)
    if method == "pillow_nearest":
        picked = np.asarray(
            Image.fromarray(ramp).resize((target, 2), Image.Resampling.NEAREST)
        )
    else:
        cv2 = _cv2()
        picked = cv2.resize(
            ramp.astype(np.float32), (target, 2), interpolation=cv2.INTER_NEAREST
        )
    return [[int(i)] for i in picked[0]]


def validate(layer):
    method = layer.get("method")
    if method not in ATTACKABLE or method not in {item["id"] for item in methods()}:
        raise ValueError(f"A scaling attack needs one of: {', '.join(ATTACKABLE)}.")
    text = layer.get("text")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("A scaling layer needs text.")
    clean = {"method": method, "text": text, "panel": layer.get("panel") is True}
    for key in ("width", "size", "x", "y"):
        if not isinstance(layer.get(key), (int, float)):
            raise ValueError(f"A scaling layer needs a numeric {key}.")
        clean[key] = layer[key]
    for key in ("color", "panel_color"):
        clean[key] = _color(layer.get(key, "#000000"))
    return clean


def _color(value):
    if not isinstance(value, str) or len(value) != 7 or value[0] != "#":
        raise ValueError("Colours are #rrggbb.")
    return tuple(int(value[index : index + 2], 16) for index in (1, 3, 5))


def payload(image, layer):
    """The downscaled image with the layer's text drawn in, and its size."""
    size = target_size(image.size, layer["width"])
    base = downscale(image, layer["method"], size)
    drawn = base.copy()
    draw = ImageDraw.Draw(drawn)
    font = ImageFont.truetype(str(FONT), max(1, round(layer["size"])))
    ratio = size[0] / image.size[0]
    center = (layer["x"] * ratio, layer["y"] * ratio)
    if layer["panel"]:
        box = draw.multiline_textbbox(
            center, layer["text"], font=font, anchor="mm", align="center"
        )
        pad = max(2, round(layer["size"] / 3))
        draw.rectangle(
            (box[0] - pad, box[1] - pad, box[2] + pad, box[3] + pad),
            fill=layer["panel_color"],
        )
    draw.multiline_text(
        center,
        layer["text"],
        font=font,
        fill=layer["color"],
        anchor="mm",
        align="center",
    )
    return base, drawn


def embed(image, layer):
    """Write the payload into exactly the pixels the resizer samples.

    Returns the new image, the intended downscaled image and the mask of
    output pixels the text changed.
    """
    base, drawn = payload(image, layer)
    source = np.array(image)
    target = np.asarray(drawn)
    mask = (np.asarray(base) != target).any(axis=2)
    columns = sampled(layer["method"], image.size[0], drawn.size[0])
    rows = sampled(layer["method"], image.size[1], drawn.size[1])
    for y, x in np.argwhere(mask):
        for row in rows[y]:
            for column in columns[x]:
                source[row, column] = target[y, x]
    return Image.fromarray(source), drawn, mask


def check(data, layer, drawn, mask):
    """How many of the changed output pixels the resizer reproduces exactly."""
    with Image.open(BytesIO(data)) as image:
        rgb = image.convert("RGB")
    got = np.asarray(downscale(rgb, layer["method"], drawn.size))
    exact = (got == np.asarray(drawn)).all(axis=2)
    return int(exact[mask].sum()), int(mask.sum())
