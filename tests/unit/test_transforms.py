import numpy as np
import pytest
from PIL import Image

from vipi.ocr.measured_transforms import CONTRASTS, orientation_view

from vipi.ocr.transforms import (
    apply_filter,
    decode_image,
    render_view,
    tile_starts,
)


@pytest.mark.parametrize("angle", [90, 180, 270])
def test_rotation_pixels_and_inverse_mapping(angle):
    pixels = np.zeros((7, 11, 3), dtype=np.uint8)
    pixels[2, 8] = 255
    original = Image.fromarray(pixels)
    view = orientation_view(11, 7, f"rotate-{angle}")
    rendered = np.array(render_view(original, view))
    y, x = np.argwhere(rendered[:, :, 0] == 255)[0]
    assert view.map_polygon([(x + 0.5, y + 0.5)])[0] == [8.5, 2.5]
    assert (rendered.shape[1], rendered.shape[0]) == (view.width, view.height)


def test_image_decoder_can_defer_the_application_pixel_limit(tmp_path):
    source = tmp_path / "large.png"
    Image.new("RGB", (40, 30), (25, 50, 75)).save(source)

    with pytest.raises(ValueError, match="0.001199 megapixels"):
        decode_image(source, max_pixels=1200 - 1)
    assert decode_image(source, max_pixels=None).size == (40, 30)


def test_filters_start_independently_and_keep_geometry():
    image = Image.new("RGB", (7, 5), (30, 100, 200))
    before = np.array(image).copy()
    for name in CONTRASTS:
        result = apply_filter(image, name)
        assert result.mode == "RGB" and result.size == image.size
        assert np.array_equal(np.array(image), before)
    assert apply_filter(image, "inverted").getpixel((0, 0)) == (225, 155, 55)


def test_color_contrast_separates_faint_achromatic_strokes_from_color_background():
    pixels = np.full((81, 121, 3), (180, 30, 30), dtype=np.uint8)
    pixels[20:61, 50:55] = (190, 65, 65)
    image = Image.fromarray(pixels)
    result = apply_filter(image, "saturation-blackhat61")
    assert result.getpixel((52, 40)) == (0, 0, 0)
    assert result.getpixel((10, 40)) == (255, 255, 255)
    assert np.array_equal(np.asarray(image), pixels)


def test_color_contrast_is_blank_when_achromatic_pixels_have_no_saturation_signal():
    pixels = np.full((81, 121, 3), 255, dtype=np.uint8)
    pixels[20:61, 50:55] = 80
    result = apply_filter(Image.fromarray(pixels), "saturation-blackhat61")
    assert np.all(np.asarray(result) == 255)


def test_decode_alpha_exif_and_static_validation(tmp_path):
    path = tmp_path / "alpha.png"
    Image.new("RGBA", (2, 2), (0, 0, 0, 0)).save(path)
    original = path.read_bytes()
    assert decode_image(path).getpixel((0, 0)) == (255, 255, 255)
    assert path.read_bytes() == original
    animation = tmp_path / "animated.png"
    Image.new("RGB", (2, 2), "white").save(
        animation, save_all=True, append_images=[Image.new("RGB", (2, 2), "black")]
    )
    with pytest.raises(ValueError, match="static"):
        decode_image(animation)
    jpeg = tmp_path / "rotated.jpg"
    exif = Image.Exif()
    exif[274] = 6
    Image.new("RGB", (9, 5), "white").save(jpeg, exif=exif)
    assert decode_image(jpeg).size == (5, 9)


def test_source_tile_edge_coverage():
    assert tile_starts(1) == [0]
    assert tile_starts(2500) == [0, 896, 1476]
