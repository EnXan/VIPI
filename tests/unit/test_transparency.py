"""Views of transparent images: construction and deduplication (ADR 0085)."""

from io import BytesIO

import numpy as np
from PIL import Image
import pytest

from tests.transparency_cases import CASES, VISIBLE_CONTRAST, opaque_rgba, text_mask
from vipi.images import decode_image
from vipi.transparency import VIEWS, read_views


def contrast(png):
    gray = np.asarray(Image.open(BytesIO(png)).convert("L")).astype(float)
    mask = text_mask()
    return abs(gray[mask].mean() - gray[~mask].mean())


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.id)
def test_views(case):
    views = read_views(BytesIO(case.encode()))
    assert [view.name for view in views.views] == list(VIEWS)
    assert [view.name for view in views.distinct] == list(case.distinct)
    for view in views.views:
        if view.same_as is not None:
            assert view.png == views.view(view.same_as).png
        image = Image.open(BytesIO(view.png))
        assert image.mode == "RGB"
        visible = contrast(view.png) >= VISIBLE_CONTRAST
        assert visible == (view.name in case.visible), view.name


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.id)
def test_white_view_is_the_decoded_image(case):
    """The white view is what VIPI scans for every other image."""
    data = case.encode()
    white = read_views(BytesIO(data)).view("white").png
    decoded = decode_image(BytesIO(data))
    assert np.array_equal(np.asarray(Image.open(BytesIO(white))), np.asarray(decoded))


def png(pixels, mode=None):
    buffer = BytesIO()
    Image.fromarray(pixels, *(() if mode is None else (mode,))).save(buffer, "PNG")
    return BytesIO(buffer.getvalue())


def test_opaque_images_have_no_views(tmp_path):
    assert read_views(png(opaque_rgba())) is None
    assert read_views(png(opaque_rgba()[..., :3])) is None
    path = tmp_path / "photo.jpg"
    Image.fromarray(opaque_rgba()[..., :3]).save(path)
    assert read_views(path) is None


def test_one_transparent_pixel_is_enough():
    pixels = opaque_rgba()
    pixels[0, 0, 3] = 254
    assert read_views(png(pixels)) is not None


def test_views_follow_exif_orientation():
    image = Image.fromarray(CASES[0].pixels)
    exif = Image.Exif()
    exif[0x0112] = 6  # rotate 90° clockwise for display
    buffer = BytesIO()
    image.save(buffer, "PNG", exif=exif)
    views = read_views(BytesIO(buffer.getvalue()))
    shown = Image.open(BytesIO(views.view("black").png))
    assert shown.size == (image.height, image.width)


def test_oversized_and_animated_inputs_fail_like_decoding():
    with pytest.raises(ValueError, match="megapixels"):
        read_views(png(CASES[0].pixels), max_pixels=100)
    frames = [Image.fromarray(CASES[0].pixels) for _ in range(2)]
    buffer = BytesIO()
    frames[0].save(buffer, "PNG", save_all=True, append_images=frames[1:])
    with pytest.raises(ValueError, match="static PNG"):
        read_views(BytesIO(buffer.getvalue()))


def test_report_lists_views_and_scores():
    views = read_views(BytesIO(CASES[1].encode()))
    answers = [
        {"status": "completed", "probability": 0.1, "source_ids": ["assembled"]},
        {"status": "completed", "probability": 0.9, "source_ids": ["ocr_rgb"]},
        {"status": "completed", "probability": 0.2, "source_ids": ["ocr_black"]},
        {"status": "completed", "probability": 0.7, "kind": "image", "view": "rgb"},
    ]
    report = views.report(answers)
    assert [item["name"] for item in report["views"]] == list(VIEWS)
    scores = {item["name"]: item["score"] for item in report["views"]}
    assert scores == {"white": 0.1, "black": 0.2, "rgb": 0.9}
    image = {item["name"]: item.get("image_check") for item in report["views"]}
    assert image["rgb"]["probability"] == 0.7
    assert image["white"] is None
