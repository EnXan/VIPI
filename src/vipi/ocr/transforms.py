"""Render OCR recovery views in source coordinates."""

from dataclasses import dataclass
import numpy as np
from PIL import Image, ImageOps

from vipi.images import MAX_INPUT_PIXELS as MAX_INPUT_PIXELS
from vipi.images import decode_image as decode_image

TWO_TIMES_MAX_PIXELS = 8_000_000


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
