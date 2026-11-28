"""Remove painted areas from a background image with what surrounds them.

The editor's Remove brush and text selection mark areas (for example text in a
screenshot). Each connected marked area is filled by one of three methods,
whichever predicts the band of pixels just around the area best:

- **flat**: the most frequent colour of the band; exact on flat interface
  backgrounds and taken whenever it fits within ``FLAT_TOLERANCE``;
- **smooth**: a quadratic colour surface fitted to the band, robust against
  leftover glyph pixels; for fades, gradients and vignettes;
- **copy**: the pixels at the place in the image whose surroundings match the
  band best (OpenCV template matching with a mask), for patterns and textures,
  and for fades along one axis.
"""

from io import BytesIO

import numpy as np
from PIL import Image, UnidentifiedImageError

BAND = 4  # px around an area that each method must predict
FLAT_TOLERANCE = 4.0  # mean squared error per channel (about 2 levels): flat fits
OUTLIER_FACTOR = 2.5  # residuals beyond this times the median are refitted without
# The copy method searches this many times the area's size around it (at least
# SEARCH_MIN px): nearby surroundings match best, and searching a whole large
# photo per area took 0.6 s, too slow for a brush that refills on every stroke.
SEARCH_REACH = 3
SEARCH_MIN = 64


def _open(data, what):
    try:
        with Image.open(BytesIO(data)) as image:
            return image.convert("RGB") if what == "image" else image.convert("L")
    except (UnidentifiedImageError, OSError):
        raise ValueError(f"The {what} could not be decoded.") from None


def _flat(values):
    colours, counts = np.unique(values.astype(np.uint8), axis=0, return_counts=True)
    colour = colours[counts.argmax()].astype(np.float32)
    return np.mean((values - colour) ** 2), lambda points: colour


def _terms(points, centre, size):
    y, x = ((points - centre) / size).T
    return np.stack([np.ones_like(x), x, y, x * x, x * y, y * y], axis=1)


def _smooth(band_points, values, centre, size):
    terms = _terms(band_points, centre, size)
    keep = np.ones(len(values), bool)
    for _ in range(2):  # fit, drop leftover glyph pixels, fit again
        coefficients, *_ = np.linalg.lstsq(terms[keep], values[keep], rcond=None)
        residual = np.linalg.norm(terms @ coefficients - values, axis=1)
        keep = residual <= OUTLIER_FACTOR * max(np.median(residual), 1.0)
    error = np.mean((terms @ coefficients - values) ** 2)
    return error, lambda points: _terms(points, centre, size) @ coefficients


def _copy(pixels, marked, area, band, box):
    import cv2

    (y0, x0), (y1, x1) = box
    reach = np.maximum(SEARCH_REACH * np.array([y1 - y0, x1 - x0]), SEARCH_MIN)
    (sy0, sx0) = np.maximum(np.array([y0, x0]) - reach, 0)
    (sy1, sx1) = np.minimum(np.array([y1, x1]) + reach, pixels.shape[:2])
    search = pixels[sy0:sy1, sx0:sx1]
    template, weights = pixels[y0:y1, x0:x1], band[y0:y1, x0:x1].astype(np.float32)
    if template.shape[0] >= search.shape[0] or template.shape[1] >= search.shape[1]:
        return np.inf, None
    distance = cv2.matchTemplate(
        search, template, cv2.TM_SQDIFF, mask=np.dstack([weights] * 3)
    )
    # A source window must not reach into any marked pixel where it copies from.
    overlap = cv2.matchTemplate(
        marked[sy0:sy1, sx0:sx1].astype(np.float32),
        area[y0:y1, x0:x1].astype(np.float32),
        cv2.TM_CCORR,
    )
    distance[overlap > 0.5] = np.inf
    if not np.isfinite(distance).any():
        return np.inf, None
    sy, sx = np.unravel_index(np.argmin(distance), distance.shape)
    error = distance[sy, sx] / (weights.sum() * 3)
    sy, sx = sy + sy0, sx + sx0
    return error, lambda points: pixels[points[:, 0] - y0 + sy, points[:, 1] - x0 + sx]


def _fill(pixels, marked, area):
    import cv2

    kernel = np.ones((2 * BAND + 1, 2 * BAND + 1), np.uint8)
    band = cv2.dilate(area.astype(np.uint8), kernel).astype(bool) & ~marked
    if not band.any():  # a mask covering the whole image has no surroundings
        return
    band_points, points = np.argwhere(band), np.argwhere(area)
    values = pixels[band]
    error, predict = _flat(values)
    if error > FLAT_TOLERANCE:
        low, high = band_points.min(0), band_points.max(0) + 1
        centre, size = band_points.mean(0), np.maximum(high - low, 1)
        for candidate in (
            _smooth(band_points, values, centre, size),
            _copy(pixels, marked, area, band, (tuple(low), tuple(high))),
        ):
            if candidate[0] < error:
                error, predict = candidate
    pixels[area] = predict(points)


def heal(image_png, mask_png):
    """PNG of the image with every marked (non-black) mask area filled."""
    import cv2

    image, mask = _open(image_png, "image"), _open(mask_png, "mask")
    if image.size != mask.size:
        raise ValueError("The mask must have the image's size.")
    pixels = np.asarray(image, dtype=np.float32).copy()
    marked = np.asarray(mask) > 0
    count, labels = cv2.connectedComponents(marked.astype(np.uint8), connectivity=8)
    for label in range(1, count):
        _fill(pixels, marked, labels == label)
    filled = np.clip(np.rint(pixels), 0, 255).astype(np.uint8)
    buffer = BytesIO()
    Image.fromarray(filled).save(buffer, "PNG")
    return buffer.getvalue()
