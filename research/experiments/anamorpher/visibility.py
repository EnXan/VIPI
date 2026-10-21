"""Joint bounded compensation for two 4:1 RGB nearest views.

The two sampled pixels remain fixed. Free pixels minimize squared change while
matching the carrier's block sum whenever that sum is attainable in RGB8.
"""

import numpy as np

FREE = np.array([index for index in range(16) if index not in (0, 10)])


def blocks(image):
    height, width, channels = image.shape
    if channels != 3 or height % 4 or width % 4:
        raise ValueError("Use RGB images with dimensions divisible by four.")
    return (
        image.reshape(height // 4, 4, width // 4, 4, 3)
        .transpose(0, 2, 1, 3, 4)
        .reshape(height // 4, width // 4, 16, 3)
    )


def raster(values):
    height, width = values.shape[:2]
    return (
        values.reshape(height, width, 4, 4, 3)
        .transpose(0, 2, 1, 3, 4)
        .reshape(height * 4, width * 4, 3)
    )


def tone_map(source, margin):
    if not 0 <= margin <= 32:
        raise ValueError("Use a headroom margin between 0 and 32.")
    return np.rint(
        margin + source.astype(np.float32) * (255 - 2 * margin) / 255
    ).astype(np.uint8)


def compensate(source, normal, alternate, *, rows=48):
    source = np.asarray(source)
    normal = np.asarray(normal)
    alternate = np.asarray(alternate)
    if any(image.dtype != np.uint8 for image in (source, normal, alternate)):
        raise ValueError("Use RGB8 arrays.")
    source_blocks = blocks(source)
    if normal.shape != alternate.shape or normal.shape != (*source_blocks.shape[:2], 3):
        raise ValueError(
            "Both references must have the carrier's exact 4:1 dimensions."
        )
    output = np.empty_like(source)
    feasible_count = 0
    channel_count = normal.size
    for start in range(0, normal.shape[0], rows):
        stop = min(start + rows, normal.shape[0])
        original = source_blocks[start:stop]
        free = original[:, :, FREE, :].astype(np.float32)
        desired = (
            original.sum(axis=2, dtype=np.int32)
            - normal[start:stop].astype(np.int32)
            - alternate[start:stop].astype(np.int32)
        )
        feasible = (desired >= 0) & (desired <= 14 * 255)
        feasible_count += int(feasible.sum())
        attainable = np.clip(desired, 0, 14 * 255)
        lower = np.full(attainable.shape, -255.0, dtype=np.float32)
        upper = np.full(attainable.shape, 255.0, dtype=np.float32)
        # Projection onto a box-constrained sum: every unsaturated free pixel
        # receives the same shift. Saturated pixels are handled by bisection.
        for _ in range(24):
            shift = (lower + upper) / 2
            total = np.clip(free + shift[:, :, None, :], 0, 255).sum(axis=2)
            lower = np.where(total < attainable, shift, lower)
            upper = np.where(total < attainable, upper, shift)
        projected = np.clip(free + ((lower + upper) / 2)[:, :, None, :], 0, 255)
        quantized = np.rint(projected).astype(np.int16)
        residual = attainable - quantized.sum(axis=2, dtype=np.int32)
        # Repair rounding without disturbing either reference sample. Choose
        # the cheapest integer corrections and preserve the block sum exactly.
        direction = np.sign(residual)
        cost = direction[:, :, None, :] * (quantized - projected)
        allowed = np.where(direction[:, :, None, :] > 0, quantized < 255, quantized > 0)
        cost = np.where(allowed, cost, np.inf)
        rank = np.argsort(np.argsort(cost, axis=2), axis=2)
        corrections = rank < np.abs(residual)[:, :, None, :]
        quantized += (corrections * direction[:, :, None, :]).astype(np.int16)
        result = original.copy()
        result[:, :, FREE, :] = quantized.astype(np.uint8)
        result[:, :, 0, :] = normal[start:stop]
        result[:, :, 10, :] = alternate[start:stop]
        output[start * 4 : stop * 4] = raster(result)
        if not np.array_equal(quantized.sum(axis=2), attainable):
            raise AssertionError(
                "Integer projection failed to match the attainable sum."
            )
    return output, {
        "feasible_channel_fraction": feasible_count / channel_count,
        "space": "sRGB byte values; matches typical non-linear raster averaging",
        "fixed_samples": [[0, 0], [2, 2]],
    }
