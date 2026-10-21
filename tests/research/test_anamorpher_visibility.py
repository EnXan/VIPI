import importlib.util
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

spec = importlib.util.spec_from_file_location(
    "anamorpher_visibility",
    Path(__file__).resolve().parents[2]
    / "research/experiments/anamorpher/visibility.py",
)
visibility = importlib.util.module_from_spec(spec)
spec.loader.exec_module(visibility)


def test_joint_compensation_preserves_real_sampler_views_and_exact_block_sums():
    rng = np.random.default_rng(20261012)
    source = rng.integers(32, 224, (32, 48, 3), dtype=np.uint8)
    normal = rng.integers(0, 256, (8, 12, 3), dtype=np.uint8)
    alternate = rng.integers(0, 256, (8, 12, 3), dtype=np.uint8)
    result, report = visibility.compensate(source, normal, alternate, rows=3)
    assert report["feasible_channel_fraction"] == 1
    assert np.array_equal(
        cv2.resize(result, (12, 8), interpolation=cv2.INTER_NEAREST), normal
    )
    assert np.array_equal(
        np.asarray(Image.fromarray(result).resize((12, 8), Image.Resampling.NEAREST)),
        alternate,
    )
    assert np.array_equal(
        visibility.blocks(result).sum(axis=2), visibility.blocks(source).sum(axis=2)
    )


def test_white_background_reports_the_unavoidable_dark_sample_mean_change():
    source = np.full((8, 12, 3), 255, dtype=np.uint8)
    normal = np.full((2, 3, 3), 255, dtype=np.uint8)
    alternate = np.zeros((2, 3, 3), dtype=np.uint8)
    result, report = visibility.compensate(source, normal, alternate)
    assert report["feasible_channel_fraction"] == 0
    assert np.all(visibility.blocks(result).sum(axis=2) == 15 * 255)
    assert np.all(result[2::4, 2::4] == 0)


def test_reserved_headroom_handles_both_extreme_targets():
    for value, target in ((32, 255), (223, 0)):
        source = np.full((8, 8, 3), value, dtype=np.uint8)
        normal = alternate = np.full((2, 2, 3), target, dtype=np.uint8)
        result, report = visibility.compensate(source, normal, alternate)
        assert report["feasible_channel_fraction"] == 1
        assert np.array_equal(
            visibility.blocks(result).sum(axis=2), visibility.blocks(source).sum(axis=2)
        )
