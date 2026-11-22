"""Decode image inputs and prepare whole rasters for hosted image decisions."""

from io import BytesIO
import math

from PIL import Image, ImageOps

MAX_INPUT_PIXELS = 40_000_000
OPENAI_PATCH_SIZE = 32
OPENAI_MAX_IMAGE_PATCHES = 30_000


def decode_image(source, *, max_pixels=MAX_INPUT_PIXELS):
    with Image.open(source) as image:
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


def decision_preview(image, maximum=1568):
    """Fit the provider or local preview dimensions without cropping."""
    preview = image.convert("RGB")
    if maximum is not None:
        preview.thumbnail((maximum, maximum), Image.Resampling.LANCZOS)
    return ImageOps.expand(
        preview,
        (0, 0, max(0, 280 - preview.width), max(0, 280 - preview.height)),
        fill="white",
    )


def openai_decision_image(image):
    """Keep full-size input unless it exceeds OpenAI's image patch limit."""
    raster = image.convert("RGB")
    width, height = raster.size

    def patch_count(size):
        width, height = size
        return math.ceil(width / OPENAI_PATCH_SIZE) * math.ceil(
            height / OPENAI_PATCH_SIZE
        )

    if patch_count(raster.size) <= OPENAI_MAX_IMAGE_PATCHES:
        return raster

    scale = math.sqrt(OPENAI_MAX_IMAGE_PATCHES / patch_count(raster.size))
    while True:
        target = (max(1, int(width * scale)), max(1, int(height * scale)))
        if patch_count(target) <= OPENAI_MAX_IMAGE_PATCHES:
            return raster.resize(target, Image.Resampling.LANCZOS)
        scale *= 0.99


def png_bytes(image):
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
