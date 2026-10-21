"""Controls for the normal/alternative view objective and actual Pillow kernel."""

from pathlib import Path
import sys

import cv2
import numpy as np
from PIL import Image

EXPERIMENT = (
    Path(__file__).resolve().parents[2] / "research/experiments/anamorpher"
)
sys.path.insert(0, str(EXPERIMENT))
from dual_view import (  # noqa: E402
    Lanczos,
    construct_dual,
    view_difference_bounds,
    white_target_bounds,
)
from triangle import Chain  # noqa: E402


def test_lanczos_matches_actual_pillow_float_raster():
    rng = np.random.default_rng(92)
    values = rng.uniform(40, 210, (41, 53)).astype(np.float32)
    expected = np.asarray(
        Image.fromarray(values).resize((13, 11), Image.Resampling.LANCZOS)
    )
    actual = Lanczos((53, 41), (13, 11)).forward(values[..., None])[..., 0]
    np.testing.assert_allclose(actual, expected, atol=0.0001, rtol=0.00001)


def test_lanczos_adjoint():
    rng = np.random.default_rng(2)
    source = rng.normal(size=(19, 27, 1)).astype(np.float32)
    residual = rng.normal(size=(9, 13, 1)).astype(np.float32)
    operator = Lanczos((27, 19), (13, 9))
    np.testing.assert_allclose(
        np.sum(operator.forward(source) * residual),
        np.sum(source * operator.adjoint(residual)),
        atol=0.00001,
        rtol=0.00001,
    )


def test_joint_objective_succeeds_for_disjoint_real_nearest_controls():
    # A positive control: these two physical samplers have independent pixels,
    # so failure in the smooth case cannot be excused by a broken dual solver.
    class Sample:
        bound = 1

        def __init__(self, offset):
            self.offset = offset

        def forward(self, image):
            return image[self.offset :: 4, self.offset :: 4]

        def adjoint(self, residual):
            result = np.zeros((32, 32, 3), dtype=np.float32)
            result[self.offset :: 4, self.offset :: 4] = residual
            return result

    normal = np.full((8, 8, 3), 220, dtype=np.uint8)
    normal[1:3, 1:3] = 30
    alternate = np.full((8, 8, 3), 200, dtype=np.uint8)
    alternate[4:6, 4:6] = 40
    carrier = np.full((32, 32, 3), 180, dtype=np.uint8)
    result, _ = construct_dual(
        carrier, normal, alternate, Sample(0), Sample(2), preservation=0, iterations=40
    )
    np.testing.assert_array_equal(
        cv2.resize(result, (8, 8), interpolation=cv2.INTER_NEAREST), normal
    )
    np.testing.assert_array_equal(
        np.asarray(Image.fromarray(result).resize((8, 8), Image.Resampling.NEAREST)),
        alternate,
    )


def test_bounds_reject_contradictory_identity_views():
    size = (8, 6)
    normal = np.zeros((6, 8, 1), dtype=np.uint8)
    alternate = np.full_like(normal, 255)
    bounds = view_difference_bounds(
        normal, alternate, Lanczos(size, size), Chain([size, size])
    )
    assert bounds["violating_sampled_pixels"] == 48
    assert bounds["minimum_at_least_one_view_max_pixel_error"] > 120


def test_bounds_accept_views_from_the_same_real_image():
    rng = np.random.default_rng(12)
    source = rng.integers(0, 256, (24, 32, 1), dtype=np.uint8)
    normal_operator = Lanczos((32, 24), (8, 6))
    alternate_operator = Chain([(32, 24), (16, 12)])
    normal = np.asarray(
        Image.fromarray(source[..., 0]).resize((8, 6), Image.Resampling.LANCZOS)
    )[..., None]
    alternate = alternate_operator.resize(source)
    bounds = view_difference_bounds(
        normal, alternate, normal_operator, alternate_operator
    )
    assert bounds["violating_sampled_pixels"] == 0


def test_white_bounds_reject_black_normal_and_white_triangle_identity():
    size = (8, 6)
    normal = np.zeros((6, 8, 1), dtype=np.uint8)
    alternate = np.full_like(normal, 255)
    bounds = white_target_bounds(
        normal, alternate, Lanczos(size, size), Chain([size, size])
    )
    assert bounds["violating_sampled_pixels"] == 32
    assert bounds["worst"]["gap"] > 250


def test_white_bounds_accept_actual_views_of_one_bounded_source():
    rng = np.random.default_rng(52)
    source = np.full((24, 32, 1), 255, dtype=np.uint8)
    source[8:16, 8:24] = rng.integers(0, 256, (8, 16, 1), dtype=np.uint8)
    normal_operator = Lanczos((32, 24), (8, 6))
    alternate_operator = Chain([(32, 24), (16, 12)])
    normal = np.asarray(
        Image.fromarray(source[..., 0]).resize((8, 6), Image.Resampling.LANCZOS)
    )[..., None]
    bounds = white_target_bounds(
        normal, alternate_operator.resize(source), normal_operator, alternate_operator
    )
    assert bounds["violating_sampled_pixels"] == 0
