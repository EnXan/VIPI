import numpy as np
import pytest
from PIL import Image

from vipi.ocr.transforms import (
    FILTERS,
    OCR_PROFILE,
    OCR_PROFILE_PASSES,
    apply_filter,
    decode_image,
    production_passes_for_size,
    render_view,
    resize,
    tile_starts,
    views_for_size,
)


def test_sequence_and_tile_edge_coverage():
    views = views_for_size(1301, 1103)
    assert len([view for view in views if view.backend != "tile"]) == 32
    assert len(FILTERS) == 6
    assert tile_starts(1) == [0]
    assert tile_starts(2500) == [0, 896, 1476]
    for factor in (1, 2):
        tiles = [
            view for view in views if view.backend == "tile" and view.factor == factor
        ]
        assert max(view.crop[2] for view in tiles) == 1301 * factor
        assert max(view.crop[3] for view in tiles) == 1103 * factor
        for view in tiles:
            assert view.width <= 1024 and view.height <= 1024
            assert view.map_polygon([(0, 0)])[0] == [
                view.crop[0] / factor,
                view.crop[1] / factor,
            ]


def test_reduced_transform_profile_and_large_image_skip():
    passes = production_passes_for_size(16, 12)
    assert OCR_PROFILE == "reduced-transforms-v2"
    assert [(view.id, name) for view, name in passes] == list(OCR_PROFILE_PASSES)
    assert len(passes) == 15
    assert len(production_passes_for_size(3200, 3200)) == 14
    assert len(production_passes_for_size(2000, 1000)) == 15
    assert len(production_passes_for_size(2001, 1000)) == 14
    assert all(view.backend not in {"tile", "pytorch", "tensorflow"} for view, _ in passes)


@pytest.mark.parametrize("angle", [90, 180, 270])
def test_rotation_pixels_and_inverse_mapping(angle):
    pixels = np.zeros((7, 11, 3), dtype=np.uint8)
    pixels[2, 8] = 255
    original = Image.fromarray(pixels)
    view = next(view for view in views_for_size(11, 7) if view.rotation == angle)
    rendered = np.array(render_view(original, view))
    y, x = np.argwhere(rendered[:, :, 0] == 255)[0]
    assert view.map_polygon([(x + 0.5, y + 0.5)])[0] == [8.5, 2.5]
    assert (rendered.shape[1], rendered.shape[0]) == (view.width, view.height)


def test_floor_dimensions_and_actual_mapping():
    view = next(
        view
        for view in views_for_size(11, 7)
        if view.backend == "opencv" and view.factor == 0.25
    )
    assert (view.width, view.height) == (2, 1)
    assert view.map_polygon([(2, 1)])[0] == [11, 7]
    assert min(view.width for view in views_for_size(1, 1)) == 1
    with pytest.raises(ValueError, match="80 megapixels"):
        views_for_size(5000, 5000)


def test_nearest_sampling_phases():
    pixels = np.arange(8 * 8, dtype=np.uint8).reshape(8, 8)
    image = Image.fromarray(np.repeat(pixels[..., None], 3, axis=2))
    for backend in ("opencv", "pytorch"):
        assert np.array(resize(image, backend, "nearest", (2, 2)))[
            :, :, 0
        ].tolist() == [[0, 4], [32, 36]]
    for backend in ("pillow", "tensorflow"):
        assert np.array(resize(image, backend, "nearest", (2, 2)))[
            :, :, 0
        ].tolist() == [[18, 22], [50, 54]]


def test_filters_start_independently_and_keep_geometry():
    image = Image.new("RGB", (7, 5), (30, 100, 200))
    before = np.array(image).copy()
    for name in FILTERS:
        result = apply_filter(image, name)
        assert result.mode == "RGB" and result.size == image.size
        assert np.array_equal(np.array(image), before)
    assert apply_filter(image, "inverted").getpixel((0, 0)) == (225, 155, 55)


def test_color_contrast_separates_faint_achromatic_strokes_from_color_background():
    pixels = np.full((81, 121, 3), (180, 30, 30), dtype=np.uint8)
    pixels[20:61, 50:55] = (190, 65, 65)
    image = Image.fromarray(pixels)
    result = apply_filter(image, "color-contrast")
    assert result.getpixel((52, 40)) == (0, 0, 0)
    assert result.getpixel((10, 40)) == (255, 255, 255)
    assert np.array_equal(np.asarray(image), pixels)


def test_color_contrast_is_blank_when_achromatic_pixels_have_no_saturation_signal():
    pixels = np.full((81, 121, 3), 255, dtype=np.uint8)
    pixels[20:61, 50:55] = 80
    result = apply_filter(Image.fromarray(pixels), "color-contrast")
    assert np.all(np.asarray(result) == 255)


def test_tensorflow_resize_leaves_gpu_memory_to_ocr(monkeypatch):
    import tensorflow as tf
    from vipi.ocr.transforms import _tensorflow_cpu

    _tensorflow_cpu.cache_clear()
    calls = []
    original = tf.config.set_visible_devices

    def set_visible(devices, device_type):
        calls.append((devices, device_type))
        original(devices, device_type)

    monkeypatch.setattr(tf.config, "set_visible_devices", set_visible)
    image = Image.new("RGB", (8, 8), "white")
    for method in ["nearest", "bilinear"]:
        assert resize(image, "tensorflow", method, (2, 2)).size == (2, 2)
    assert calls == [([], "GPU")]
    assert tf.config.get_visible_devices("GPU") == []


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
