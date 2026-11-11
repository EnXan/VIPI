"""Decode scan inputs and render the recovery views in source coordinates."""

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

MAX_INPUT_PIXELS = 40_000_000
TWO_TIMES_MAX_PIXELS = 8_000_000


def decode_image(path: str | Path, *, max_pixels=MAX_INPUT_PIXELS) -> Image.Image:
    with Image.open(path) as image:
        if (
            image.format not in {"PNG", "JPEG", "WEBP"}
            or getattr(image, "n_frames", 1) != 1
        ):
            raise ValueError("Use a static PNG, JPEG or WebP image.")
        if max_pixels is not None and image.width * image.height > max_pixels:
            raise ValueError(f"Input exceeds {max_pixels / 1_000_000:g} megapixels.")
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
    mirrored: bool = False

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


def render_view(image: Image.Image, view: View) -> Image.Image:
    if view.mirrored:
        image = ImageOps.mirror(image)
    if view.rotation:
        image = image.transpose(
            {
                90: Image.Transpose.ROTATE_270,
                180: Image.Transpose.ROTATE_180,
                270: Image.Transpose.ROTATE_90,
            }[view.rotation]
        )
    if view.crop:
        return image.crop(view.crop)
    return image


def apply_filter(image: Image.Image, name: str) -> Image.Image:
    from .measured_transforms import apply_measured_filter

    return apply_measured_filter(image, name)
