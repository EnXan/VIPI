"""The fixed transformation sequence; each raster is generated on demand."""

from dataclasses import dataclass
from functools import cache
from pathlib import Path
import threading

import cv2
import numpy as np
from PIL import Image, ImageOps

MAX_INPUT_PIXELS = 40_000_000
MAX_VIEW_PIXELS = 80_000_000
FILTERS = ("unchanged", "grayscale", "clahe", "inverted", "threshold", "color-contrast")
OCR_PROFILE = "reduced-transforms-v2"
TWO_TIMES_MAX_PIXELS = 8_000_000
OCR_PROFILE_PASSES = (
    ("original-unchanged-1x", "unchanged"),
    ("pillow-bicubic-2x", "unchanged"),
    ("pillow-nearest-0.5x", "unchanged"),
    ("opencv-bicubic-0.5x", "unchanged"),
    ("opencv-nearest-0.25x", "unchanged"),
    ("pillow-nearest-0.25x", "unchanged"),
    ("opencv-linear-exact-0.25x", "unchanged"),
    ("opencv-bicubic-0.25x", "unchanged"),
    ("rotate-90", "unchanged"),
    ("rotate-180", "unchanged"),
    ("original-unchanged-1x", "inverted"),
    ("opencv-nearest-0.125x", "grayscale"),
    ("pillow-nearest-0.125x", "unchanged"),
    ("original-unchanged-1x", "clahe"),
    ("original-unchanged-1x", "color-contrast"),
)
_tensorflow_lock = threading.Lock()


@cache
def _tensorflow_cpu():
    import tensorflow as tf

    # TensorFlow must not reserve the CUDA device used by the OCR sessions.
    tf.config.set_visible_devices([], "GPU")
    return tf


def decode_image(path: str | Path) -> Image.Image:
    with Image.open(path) as image:
        if (
            image.format not in {"PNG", "JPEG", "WEBP"}
            or getattr(image, "n_frames", 1) != 1
        ):
            raise ValueError("Use a static PNG, JPEG or WebP image.")
        if image.width * image.height > MAX_INPUT_PIXELS:
            raise ValueError("Input exceeds 40 megapixels.")
        image = ImageOps.exif_transpose(image)
        rgba = image.convert("RGBA")
        background = Image.new("RGBA", image.size, "white")
        return Image.alpha_composite(background, rgba).convert("RGB")


@dataclass(frozen=True)
class View:
    id: str
    width: int
    height: int
    # Maps continuous image boundary coordinates back to the decoded input.
    to_input: tuple[tuple[float, float, float], ...]
    backend: str = "original"
    method: str = "unchanged"
    rotation: int = 0
    crop: tuple[int, int, int, int] | None = None
    factor: float = 1.0

    def map_polygon(self, polygon):
        points = np.array([[x, y, 1] for x, y in polygon], dtype=float)
        return (points @ np.array(self.to_input).T)[:, :2].tolist()


def tile_starts(length: int) -> list[int]:
    if length <= 1024:
        return [0]
    starts = list(range(0, length - 1024 + 1, 896))
    if starts[-1] != length - 1024:
        starts.append(length - 1024)
    return starts


def views_for_size(
    width: int, height: int, *, selected_ids: set[str] | None = None
) -> list[View]:
    views = []

    def scaled(backend, method, factor):
        identifier = f"{backend}-{method}-{factor:g}x"
        if selected_ids is not None and identifier not in selected_ids:
            return None
        w, h = max(1, int(width * factor)), max(1, int(height * factor))
        if w * h > MAX_VIEW_PIXELS:
            raise ValueError("A required transformed view exceeds 80 megapixels.")
        matrix = ((width / w, 0, 0), (0, height / h, 0), (0, 0, 1))
        return View(
            identifier,
            w,
            h,
            matrix,
            backend,
            method,
            factor=factor,
        )

    def add(view):
        if view is not None:
            views.append(view)

    add(scaled("original", "unchanged", 1))
    add(scaled("pillow", "bicubic", 2))
    for factor in (0.5, 0.25, 0.125):
        for backend, methods in (
            ("pillow", ("nearest", "bilinear", "bicubic")),
            ("opencv", ("nearest", "bilinear", "linear-exact", "bicubic")),
        ):
            for method in methods:
                add(scaled(backend, method, factor))
    for backend in ("pytorch", "tensorflow"):
        for method in ("nearest", "bilinear", "bicubic"):
            add(scaled(backend, method, 0.25))
    for angle, matrix in (
        (90, ((0, 1, 0), (-1, 0, height), (0, 0, 1))),
        (180, ((-1, 0, width), (0, -1, height), (0, 0, 1))),
        (270, ((0, -1, width), (1, 0, 0), (0, 0, 1))),
    ):
        if selected_ids is not None and f"rotate-{angle}" not in selected_ids:
            continue
        w, h = (height, width) if angle != 180 else (width, height)
        add(View(f"rotate-{angle}", w, h, matrix, rotation=angle))
    if selected_ids is None:
        for factor in (1, 2):
            w, h = width * factor, height * factor
            for y in tile_starts(h):
                for x in tile_starts(w):
                    tw, th = min(1024, w), min(1024, h)
                    matrix = (
                        (1 / factor, 0, x / factor),
                        (0, 1 / factor, y / factor),
                        (0, 0, 1),
                    )
                    views.append(
                        View(
                            f"tile-{factor}x-{x}-{y}",
                            tw,
                            th,
                            matrix,
                            "tile",
                            crop=(x, y, x + tw, y + th),
                            factor=factor,
                        )
                    )
    return views


def production_passes_for_size(width: int, height: int) -> list[tuple[View, str]]:
    """Return the reduced production transform set in its fixed evidence order."""
    profile = list(OCR_PROFILE_PASSES)
    if width * 2 * height * 2 > TWO_TIMES_MAX_PIXELS:
        profile = [item for item in profile if item[0] != "pillow-bicubic-2x"]
    view_ids = {view_id for view_id, _ in profile}
    views = {
        view.id: view
        for view in views_for_size(width, height, selected_ids=view_ids)
    }
    return [(views[view_id], filter_name) for view_id, filter_name in profile]


def resize(
    image: Image.Image, backend: str, method: str, size: tuple[int, int]
) -> Image.Image:
    if backend == "pillow":
        return image.resize(size, getattr(Image.Resampling, method.upper()))
    pixels = np.asarray(image)
    if backend == "opencv":
        mode = {
            "nearest": cv2.INTER_NEAREST,
            "bilinear": cv2.INTER_LINEAR,
            "linear-exact": cv2.INTER_LINEAR_EXACT,
            "bicubic": cv2.INTER_CUBIC,
        }[method]
        result = cv2.resize(pixels, size, interpolation=mode)
    elif backend == "pytorch":
        import torch
        import torch.nn.functional as functional

        tensor = torch.from_numpy(pixels.copy().transpose(2, 0, 1)).float().unsqueeze(0)
        with torch.no_grad():
            result = functional.interpolate(
                tensor,
                size=(size[1], size[0]),
                mode=method,
                align_corners=False if method != "nearest" else None,
                antialias=False,
            )
        # Match the vendored sampler, including uint8 conversion without clipping.
        result = result.squeeze(0).permute(1, 2, 0).numpy().astype(np.uint8)
    elif backend == "tensorflow":
        with _tensorflow_lock:
            tf = _tensorflow_cpu()
        with tf.device("/CPU:0"):
            tensor = tf.expand_dims(tf.convert_to_tensor(pixels, dtype=tf.float32), 0)
            mode = "nearest" if method == "nearest" else method
            result = tf.image.resize(
                tensor, (size[1], size[0]), method=mode, antialias=False
            )
            result = tf.squeeze(result, 0).numpy().astype(np.uint8)
    else:
        raise ValueError(f"Unknown resize backend: {backend}")
    return Image.fromarray(result)


def render_view(image: Image.Image, view: View) -> Image.Image:
    if view.rotation:
        return image.transpose(
            {
                90: Image.Transpose.ROTATE_270,
                180: Image.Transpose.ROTATE_180,
                270: Image.Transpose.ROTATE_90,
            }[view.rotation]
        )
    if view.crop:
        source = (
            image
            if view.factor == 1
            else resize(image, "pillow", "bicubic", (image.width * 2, image.height * 2))
        )
        return source.crop(view.crop)
    if view.backend == "original":
        return image
    return resize(image, view.backend, view.method, (view.width, view.height))


def apply_filter(image: Image.Image, name: str) -> Image.Image:
    if name == "unchanged":
        return image
    pixels = np.asarray(image)
    gray = cv2.cvtColor(pixels, cv2.COLOR_RGB2GRAY)
    if name == "grayscale":
        result = gray
    elif name == "clahe":
        result = cv2.createCLAHE(clipLimit=2, tileGridSize=(8, 8)).apply(gray)
    elif name == "inverted":
        return Image.fromarray(255 - pixels)
    elif name == "threshold":
        result = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 11
        )
    elif name == "color-contrast":
        saturation = cv2.cvtColor(pixels, cv2.COLOR_RGB2HSV)[:, :, 1]
        strokes = cv2.morphologyEx(
            saturation,
            cv2.MORPH_BLACKHAT,
            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (61, 61)),
        )
        result = 255 - cv2.normalize(strokes, None, 0, 255, cv2.NORM_MINMAX)
    else:
        raise ValueError(f"Unknown filter: {name}")
    return Image.fromarray(result).convert("RGB")
