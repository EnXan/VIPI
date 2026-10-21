"""Neutral feasibility probe with explicit ordinary-view and scaled-view goals.

Lanczos is a continuous, float32 port of Pillow's published coefficient formula
for construction gradients. Final ordinary views are rendered by actual Pillow,
and Triangle views by the compiled scalar port. No model guides construction.
"""

import numpy as np
from scipy.sparse import csr_matrix

from research.experiments.anamorpher.triangle import Triangle, rgb8

LANCZOS_SOURCE = (
    "https://github.com/python-pillow/Pillow/blob/11.3.0/src/libImaging/Resample.c"
)


def lanczos_weights(source, target):
    if min(source, target) < 1:
        raise ValueError("Image dimensions must be positive.")
    ratio = source / target
    scale = max(1, ratio)
    support = scale * 3
    data, indices, pointers = [], [], [0]
    for output in range(target):
        center = (output + 0.5) * ratio
        left = max(0, int(center - support + 0.5))
        right = min(source, int(center + support + 0.5))
        taps = []
        for index in range(left, right):
            distance = (index - center + 0.5) / scale
            if -3 <= distance < 3:
                weight = float(np.sinc(distance) * np.sinc(distance / 3))
            else:
                weight = 0
            taps.append(weight)
        total = sum(taps)
        data.extend(weight / total for weight in taps)
        indices.extend(range(left, right))
        pointers.append(len(data))
    return csr_matrix(
        (np.array(data, dtype=np.float32), indices, pointers),
        shape=(target, source),
        dtype=np.float32,
    )


class Lanczos(Triangle):
    def __init__(self, source_size, target_size):
        self.source_size = tuple(source_size)
        self.target_size = tuple(target_size)
        self.x = lanczos_weights(source_size[0], target_size[0])
        self.y = lanczos_weights(source_size[1], target_size[1])

        # Negative Lanczos taps require absolute row and column norm bounds.
        def bound(matrix):
            absolute = abs(matrix)
            return float(np.asarray(absolute.sum(axis=0)).max()) * float(
                np.asarray(absolute.sum(axis=1)).max()
            )

        self.bound = bound(self.x) * bound(self.y)


def construct_dual(
    carrier,
    normal,
    alternate,
    normal_operator,
    alternate_operator,
    *,
    normal_weight=1,
    preservation=0.001,
    iterations=100,
    progress=None,
):
    """Minimize both image-view errors with RGB8 bounds and size-normalized losses."""
    if normal_weight <= 0 or preservation < 0 or iterations < 1:
        raise ValueError(
            "Use positive normal weight/iterations and nonnegative preservation."
        )
    original = np.asarray(carrier, dtype=np.float32)
    expected_normal = np.asarray(normal, dtype=np.float32)
    expected_alternate = np.asarray(alternate, dtype=np.float32)
    # The two views have different numbers of pixels. Equal weights must mean
    # equal mean squared errors, not equal sums of errors.
    factor = np.float32(normal_weight * expected_alternate.size / expected_normal.size)
    lipschitz = factor * normal_operator.bound + alternate_operator.bound + preservation
    step = np.float32(0.95 / lipschitz)
    pixels = original.copy()
    history = []
    for iteration in range(iterations):
        normal_error = normal_operator.forward(pixels) - expected_normal
        alternate_error = alternate_operator.forward(pixels) - expected_alternate
        gradient = factor * normal_operator.adjoint(normal_error)
        gradient += alternate_operator.adjoint(alternate_error)
        if preservation:
            gradient += np.float32(preservation) * (pixels - original)
        pixels = np.clip(pixels - step * gradient, 0, 255)
        if iteration % 20 == 0 or iteration == iterations - 1:
            entry = {
                "iteration": iteration + 1,
                "normal_rmse_before_update": float(np.sqrt(np.mean(normal_error**2))),
                "alternate_rmse_before_update": float(
                    np.sqrt(np.mean(alternate_error**2))
                ),
            }
            history.append(entry)
            if progress:
                progress(entry)
    return rgb8(pixels), history


def view_difference_bounds(
    normal, alternate, normal_operator, alternate_operator, *, samples=64
):
    """Conditional pixel bounds for the declared linear ports with RGB8 guards.

    Compare L(x) to R(T(x)), mapping the Triangle target to the normal-view size.
    Each row of L-R*T has a finite maximum/minimum over byte-bounded x. Conservative
    guards cover intermediate Lanczos clipping, byte rounding and small coefficient
    differences. A violation rules out close pixel matching of these references;
    it does not prove that two OCR interpretations cannot differ.
    """
    from triangle import Triangle

    reference = np.asarray(normal, dtype=np.float32)
    target = np.asarray(alternate, dtype=np.float32)
    reduce_target = Triangle(
        alternate_operator.stages[-1].target_size, normal_operator.target_size
    )
    required = reference - reduce_target.forward(target)
    composed_x, composed_y = reduce_target.x, reduce_target.y
    for stage in reversed(alternate_operator.stages):
        composed_x = composed_x @ stage.x
        composed_y = composed_y @ stage.y
    abs_x_rows = np.asarray(abs(normal_operator.x).sum(axis=1)).ravel()
    abs_y_rows = np.asarray(abs(normal_operator.y).sum(axis=1)).ravel()
    negative_x = np.maximum(0, (abs_x_rows - 1) / 2)
    negative_y = np.maximum(0, (abs_y_rows - 1) / 2)
    # Actual Pillow RGB8 performs a clipped, rounded horizontal pass first.
    # 0.51 includes rounding and a conservative coefficient-quantization margin.
    lanczos_guard = (
        abs_y_rows.max() * (255 * negative_x.max() + 0.51)
        + 255 * negative_y.max()
        + 0.51
    )
    # Positive Triangle stages do not amplify preceding rounding errors.
    triangle_guard = len(alternate_operator.stages) * 0.51
    numeric_guard = 2.0
    guard = float(lanczos_guard + triangle_guard + numeric_guard)
    strongest = np.max(np.abs(required), axis=2)
    count = min(samples, strongest.size)
    candidates = np.argpartition(strongest.ravel(), -count)[-count:]
    rows = []
    for index in candidates:
        y, x = np.unravel_index(index, strongest.shape)
        channel = int(np.argmax(np.abs(required[y, x])))
        lx, cx = normal_operator.x.getrow(x), composed_x.getrow(x)
        ly, cy = normal_operator.y.getrow(y), composed_y.getrow(y)
        xs, ys = np.union1d(lx.indices, cx.indices), np.union1d(ly.indices, cy.indices)

        def padded(row, indices):
            values = np.zeros(len(indices), dtype=np.float64)
            values[np.searchsorted(indices, row.indices)] = row.data
            return values

        difference = np.outer(padded(ly, ys), padded(lx, xs)) - np.outer(
            padded(cy, ys), padded(cx, xs)
        )
        lower = float(255 * np.minimum(difference, 0).sum()) - guard
        upper = float(255 * np.maximum(difference, 0).sum()) + guard
        desired = float(required[y, x, channel])
        gap = max(lower - desired, desired - upper, 0)
        rows.append(
            {
                "pixel": [int(x), int(y)],
                "channel": channel,
                "required_difference": desired,
                "guarded_attainable_interval": [lower, upper],
                "gap": gap,
            }
        )
    worst = max(rows, key=lambda row: row["gap"])
    return {
        "scope": "conditional declared linear ports and conservative RGB8/clipping guards; not an OCR impossibility proof",
        "sampled_pixels": count,
        "lanczos_guard": float(lanczos_guard),
        "triangle_guard": float(triangle_guard),
        "numeric_guard": numeric_guard,
        "violating_sampled_pixels": sum(row["gap"] > 0 for row in rows),
        "worst": worst,
        "minimum_at_least_one_view_max_pixel_error": worst["gap"] / 2,
    }


def white_target_bounds(
    normal,
    alternate,
    normal_operator,
    alternate_operator,
    *,
    alternate_tolerance=2,
    samples=32,
):
    """Conditional bounds from near-white pixels in the positive Triangle view.

    Near-white Triangle outputs constrain their contributing byte-bounded source
    pixels to be bright. Propagate those lower bounds through Pillow's horizontal
    and vertical clipping/rounding. This checks raster-reference compatibility,
    not whether an OCR model could interpret imperfect images differently.
    """
    reference = np.asarray(normal, dtype=float)
    target = np.asarray(alternate, dtype=float)
    x, y = alternate_operator.stages[-1].x, alternate_operator.stages[-1].y
    for stage in reversed(alternate_operator.stages[:-1]):
        x, y = x @ stage.x, y @ stage.y
    x, y = x.tocsc(), y.tocsc()
    source_pixel_margin = (
        alternate_tolerance + len(alternate_operator.stages) * 0.51 + 1.0
    )
    reduced = Triangle(
        alternate_operator.stages[-1].target_size, normal_operator.target_size
    ).forward(target)
    needed = np.max(reduced - reference, axis=2)
    count = min(samples, needed.size)
    candidates = np.argpartition(needed.ravel(), -count)[-count:]
    rows = []
    for position in candidates:
        oy, ox = np.unravel_index(position, needed.shape)
        channel = int(np.argmax(reduced[oy, ox] - reference[oy, ox]))
        normal_x = normal_operator.x.getrow(ox)
        normal_y = normal_operator.y.getrow(oy)
        lower_source = np.zeros((len(normal_y.indices), len(normal_x.indices)))
        for iy, sy in enumerate(normal_y.indices):
            a, b = y.indptr[sy : sy + 2]
            ys, yw = y.indices[a:b], y.data[a:b].astype(float)
            for ix, sx in enumerate(normal_x.indices):
                a, b = x.indptr[sx : sx + 2]
                xs, xw = x.indices[a:b], x.data[a:b].astype(float)
                white = target[ys[:, None], xs[None, :], channel] == 255
                strongest = float((yw[:, None] * xw[None, :] * white).max(initial=0))
                if strongest > 0:
                    lower_source[iy, ix] = max(0, 255 - source_pixel_margin / strongest)
        wx, wy = normal_x.data.astype(float), normal_y.data.astype(float)
        positive_x, negative_x = np.maximum(wx, 0), np.minimum(wx, 0)
        horizontal_lower = np.clip(
            lower_source @ positive_x + 255 * negative_x.sum() - 0.51, 0, 255
        )
        horizontal_upper = np.clip(
            255 * positive_x.sum() + lower_source @ negative_x + 0.51, 0, 255
        )
        lower = float(
            np.clip(
                np.maximum(wy, 0) @ horizontal_lower
                + np.minimum(wy, 0) @ horizontal_upper
                - 0.51,
                0,
                255,
            )
        )
        upper = float(
            np.clip(
                np.maximum(wy, 0) @ horizontal_upper
                + np.minimum(wy, 0) @ horizontal_lower
                + 0.51,
                0,
                255,
            )
        )
        desired = float(reference[oy, ox, channel])
        rows.append(
            {
                "pixel": [int(ox), int(oy)],
                "channel": channel,
                "desired_normal": desired,
                "guarded_normal_interval": [lower, upper],
                "gap": max(lower - desired, desired - upper, 0),
            }
        )
    worst = max(rows, key=lambda row: row["gap"])
    return {
        "scope": "conditional raster-reference compatibility under declared ports, byte bounds and conservative clipping/rounding guards; not an OCR impossibility proof",
        "alternate_per_pixel_tolerance": alternate_tolerance,
        "triangle_rounding_numeric_guard": source_pixel_margin - alternate_tolerance,
        "sampled_pixels": count,
        "violating_sampled_pixels": sum(row["gap"] > 0 for row in rows),
        "worst": worst,
    }
