"""Check that a readable texture survives while its scaled mean changes view."""

from pathlib import Path
import sys

import numpy as np
import pytest

EXPERIMENT = (
    Path(__file__).resolve().parents[2] / "research/experiments/anamorpher"
)
sys.path.insert(0, str(EXPERIMENT))
from frequency_pair import encode  # noqa: E402
from triangle import Triangle  # noqa: E402


def test_separate_texture_and_scaled_mean_channels():
    normal = np.full((96, 128), 255, np.uint8)
    alternate = normal.copy()
    normal[16:48, 16:48] = 35
    alternate[16:48, 80:112] = 35
    pixels, target, _ = encode(normal, alternate)
    actual = Triangle((128, 96), (64, 48)).resize(pixels[..., None])[..., 0]
    assert np.abs(actual.astype(int) - target).max() <= 1
    # Source shape remains in the texture: flat inside, high contrast outside.
    assert pixels[24:40, 24:40].std() < 1
    assert pixels[56:72, 24:40].std() > 90
    # After resizing, the first shape disappears and the different one remains.
    assert actual[12:20, 12:20].mean() == 128
    assert actual[12:20, 44:52].mean() == 120


def test_rejects_geometry_that_breaks_two_to_one_mapping():
    image = np.full((31, 32), 255, np.uint8)
    with pytest.raises(ValueError, match="even"):
        encode(image, image)
