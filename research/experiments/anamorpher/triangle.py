"""Opaque RGB Triangle resampling from image-rs 0.25.9's published formula.

Float32 centers, widened downsampling support, clipped/renormalized edge taps,
vertical then horizontal sampling, and final positive half-up rounding.
This is a source-based port, not execution of the Rust crate.
"""

import math

import numpy as np
from scipy.sparse import csr_matrix

SOURCE = "https://github.com/image-rs/image/blob/v0.25.9/src/imageops/sample.rs"


def axis_weights(source, target):
    if min(source, target) < 1:
        raise ValueError("Image dimensions must be positive.")
    ratio = np.float32(source) / np.float32(target)
    scale = max(np.float32(1), ratio)
    data, indices, pointers = [], [], [0]
    for output in range(target):
        center = (np.float32(output) + np.float32(0.5)) * ratio
        left = max(0, min(source - 1, math.floor(center - scale)))
        right = max(left + 1, min(source, math.ceil(center + scale)))
        center -= np.float32(0.5)
        taps = []
        total = np.float32(0)
        for index in range(left, right):
            distance = abs((np.float32(index) - center) / scale)
            weight = np.float32(1) - distance if distance < 1 else np.float32(0)
            taps.append(weight)
            total += weight
        data.extend(weight / total for weight in taps)
        indices.extend(range(left, right))
        pointers.append(len(data))
    return csr_matrix(
        (np.array(data, dtype=np.float32), indices, pointers),
        shape=(target, source),
        dtype=np.float32,
    )


def rgb8(values):
    return np.floor(np.clip(values, 0, 255) + np.float32(0.5)).astype(np.uint8)


class Triangle:
    def __init__(self, source_size, target_size):
        self.source_size = tuple(source_size)
        self.target_size = tuple(target_size)
        self.x = axis_weights(source_size[0], target_size[0])
        self.y = axis_weights(source_size[1], target_size[1])
        self.bound = float(np.asarray(self.x.sum(axis=0)).max()) * float(
            np.asarray(self.y.sum(axis=0)).max()
        )

    @staticmethod
    def horizontal(matrix, pixels):
        height, width, channels = pixels.shape
        return (
            (matrix @ pixels.transpose(1, 0, 2).reshape(width, -1))
            .reshape(matrix.shape[0], height, channels)
            .transpose(1, 0, 2)
        )

    def forward(self, pixels):
        pixels = np.asarray(pixels, dtype=np.float32)
        height, width, channels = pixels.shape
        if (width, height) != self.source_size:
            raise ValueError("Unexpected source raster dimensions.")
        vertical = (self.y @ pixels.reshape(height, -1)).reshape(
            self.target_size[1], width, channels
        )
        return self.horizontal(self.x, vertical)

    def adjoint(self, residual):
        residual = np.asarray(residual, dtype=np.float32)
        horizontal = self.horizontal(self.x.T, residual)
        height, width, channels = horizontal.shape
        return (self.y.T @ horizontal.reshape(height, -1)).reshape(
            self.source_size[1], width, channels
        )

    def resize(self, pixels):
        return rgb8(self.forward(pixels))


class Chain:
    def __init__(self, sizes):
        self.stages = [Triangle(a, b) for a, b in zip(sizes, sizes[1:])]
        if not self.stages:
            raise ValueError("A resize chain needs at least two sizes.")
        self.bound = math.prod(stage.bound for stage in self.stages)

    def forward(self, pixels):
        for stage in self.stages:
            pixels = stage.forward(pixels)
        return pixels

    def adjoint(self, residual):
        for stage in reversed(self.stages):
            residual = stage.adjoint(residual)
        return residual

    def resize(self, pixels):
        # Raster encoding between stages includes quantization, unlike the
        # continuous operator used during construction.
        for stage in self.stages:
            pixels = stage.resize(pixels)
        return pixels


def construct(carrier, target, operator, *, preservation, iterations=80, progress=None):
    """Bounded least squares for neutral reference images; no model queried."""
    if preservation < 0 or iterations < 1:
        raise ValueError("Use nonnegative preservation and positive iterations.")
    original = np.asarray(carrier, dtype=np.float32)
    desired = np.asarray(target, dtype=np.float32)
    pixels = original.copy()
    step = np.float32(0.95 / (operator.bound + preservation))
    history = []
    for iteration in range(iterations):
        residual = operator.forward(pixels) - desired
        gradient = operator.adjoint(residual)
        if preservation:
            gradient += np.float32(preservation) * (pixels - original)
        pixels = np.clip(pixels - step * gradient, 0, 255)
        if iteration % 10 == 0 or iteration == iterations - 1:
            entry = {
                "iteration": iteration + 1,
                "target_rmse_before_update": float(np.sqrt(np.mean(residual**2))),
                "carrier_rmse_after_update": float(
                    np.sqrt(np.mean((pixels - original) ** 2))
                ),
            }
            history.append(entry)
            if progress:
                progress(entry)
    return rgb8(pixels), history
