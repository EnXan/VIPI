"""Test the actual Triangle kernel port, its gradient and a native scalar port."""

from pathlib import Path
import shutil
import subprocess
import sys

import numpy as np
import pytest

EXPERIMENT = (
    Path(__file__).resolve().parents[2] / "research/experiments/anamorpher"
)
sys.path.insert(0, str(EXPERIMENT))
from triangle import Triangle, axis_weights, construct, rgb8  # noqa: E402


def test_known_two_to_one_triangle_weights():
    matrix = axis_weights(8, 4).toarray()
    np.testing.assert_allclose(matrix[0, :3], [3 / 7, 3 / 7, 1 / 7], atol=1e-7)
    np.testing.assert_array_equal(matrix[1, 1:5], [0.125, 0.375, 0.375, 0.125])
    np.testing.assert_allclose(matrix.sum(axis=1), 1)


def test_adjoint_matches_forward_inner_product():
    rng = np.random.default_rng(42)
    operator = Triangle((23, 17), (11, 9))
    source = rng.normal(size=(17, 23, 3)).astype(np.float32)
    residual = rng.normal(size=(9, 11, 3)).astype(np.float32)
    np.testing.assert_allclose(
        np.sum(operator.forward(source) * residual),
        np.sum(source * operator.adjoint(residual)),
        rtol=1e-5,
        atol=1e-5,
    )


def test_construction_reduces_target_error_with_valid_bytes():
    operator = Triangle((32, 24), (16, 12))
    carrier = np.full((24, 32, 3), 180, dtype=np.uint8)
    target = np.full((12, 16, 3), 180, dtype=np.uint8)
    target[4:8, 5:10] = 60
    before = np.mean((operator.forward(carrier) - target) ** 2)
    result, _ = construct(carrier, target, operator, preservation=0, iterations=60)
    assert result.dtype == np.uint8
    assert result.shape == carrier.shape
    assert np.mean((operator.resize(result).astype(float) - target) ** 2) < before / 50


def test_positive_half_up_rounding():
    np.testing.assert_array_equal(rgb8(np.array([0.5, 1.5, 254.5])), [1, 2, 255])


@pytest.fixture(scope="module")
def native_reference(tmp_path_factory):
    compiler = shutil.which("clang++")
    if not compiler:
        pytest.skip("Native scalar cross-check needs clang++.")
    binary = tmp_path_factory.mktemp("triangle-reference") / "triangle-reference"
    subprocess.run(
        [
            compiler,
            "-std=c++17",
            "-O2",
            "-ffp-contract=off",
            str(EXPERIMENT / "triangle_reference.cpp"),
            "-o",
            str(binary),
        ],
        check=True,
    )
    return binary


@pytest.mark.parametrize(
    "source_size,target_size",
    [
        ((31, 27), (13, 11)),
        ((8, 6), (2, 3)),
        ((7, 5), (12, 9)),
        ((9, 7), (9, 7)),
    ],
)
def test_against_compiled_scalar_port(
    native_reference, tmp_path, source_size, target_size
):
    rng = np.random.default_rng(73)
    source = rng.integers(0, 256, (source_size[1], source_size[0], 3), dtype=np.uint8)
    input_path, output_path = tmp_path / "input.raw", tmp_path / "output.raw"
    source.tofile(input_path)
    subprocess.run(
        [
            str(native_reference),
            str(input_path),
            str(output_path),
            *map(str, source_size),
            *map(str, target_size),
        ],
        check=True,
    )
    expected = np.fromfile(output_path, dtype=np.uint8).reshape(
        target_size[1], target_size[0], 3
    )
    actual = Triangle(source_size, target_size).resize(source)
    if target_size[0] > source_size[0] or target_size[1] > source_size[1]:
        # Sparse floating-point accumulation can straddle a rounding boundary.
        # The actual experimental output is always produced by the scalar port.
        assert np.abs(actual.astype(int) - expected.astype(int)).max() <= 1
    else:
        np.testing.assert_array_equal(actual, expected)
