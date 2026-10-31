"""Individually measured view candidates, separate from the historical profile."""

import cv2
import numpy as np
from PIL import Image, ImageChops, ImageFilter, ImageOps

from .transforms import View

ORIENTATIONS = {
    "upright": "Already upright, normally readable text; no orientation correction.",
    "rotate-90": "Rotate the entire image 90 degrees clockwise to read normally.",
    "rotate-180": "Rotate the entire image 180 degrees to read normally.",
    "rotate-270": "Rotate the entire image 90 degrees counterclockwise to read normally.",
    "mirror-0": "Flip left/right to correct horizontally mirrored text.",
    "mirror-90": "Flip left/right, then rotate 90 degrees clockwise.",
    "mirror-180": "Flip left/right, then rotate 180 degrees (vertical reflection correction).",
    "mirror-270": "Flip left/right, then rotate 90 degrees counterclockwise.",
}

CONTRASTS = {
    "unchanged": "Keep original colors; normal readable screenshots/documents.",
    "stretch-gray": "Grayscale with 2nd–98th percentile contrast stretching.",
    "stretch-rgb": "2nd–98th percentile stretching separately on RGB channels.",
    "clahe-lab": "Local contrast enhancement of LAB lightness, retaining color.",
    "saturation": "HSV saturation as grayscale; separate achromatic text from colored backgrounds.",
    "saturation-inverted": "Inverted HSV saturation; separate faint achromatic text from colored photos.",
    "saturation-clahe": "HSV saturation with local contrast enhancement.",
    "saturation-clahe-inverted": "Inverted locally enhanced HSV saturation.",
    "saturation-sauvola25": "Local Sauvola threshold on saturation (25 pixels, k=0.2).",
    "saturation-blackhat61": "Local low-saturation strokes on colorful backgrounds, 61-pixel blackhat.",
    "saturation-blackhat31": "Local low-saturation strokes, 31-pixel blackhat.",
    "saturation-blackhat91": "Local low-saturation strokes, 91-pixel blackhat.",
    "saturation-blackhat121": "Local low-saturation strokes on colorful backgrounds, 121-pixel blackhat.",
    "saturation-whitehat121": "Local high-saturation colored strokes on neutral backgrounds.",
    "saturation-minmax": "Stretch the saturation channel to its complete intensity range.",
    "saturation-minmax-inverted": "Invert full-range stretched saturation.",
    "green-minus-red": "Separate chromatic text from neutral gray texture using green minus red.",
    "blue-minus-red": "Separate chromatic text from neutral gray texture using blue minus red.",
    "green-red-minmax-inverted": "Normalize and invert green-minus-red for faint colored text.",
    "blue-red-minmax-inverted": "Normalize and invert blue-minus-red for faint colored text.",
    "gamma-bright": "Brighten RGB midtones with gamma 0.5.",
    "log-rgb": "Logarithmic RGB tone correction for faint dark midtones.",
    "inverted": "Invert all RGB colors.",
    "otsu-light": "Invert grayscale, Gaussian 5x5 denoise, then global Otsu.",
    "sauvola101": "Grayscale local Sauvola threshold (101 pixels, k=0.2).",
    "lightness-tophat31": "Local bright grayscale strokes, 31-pixel elliptical top-hat.",
    "combined-strokes61": "Maximum of 61-pixel saturation blackhat and grayscale top-hat, normalized and inverted.",
    "white-saliency": "Local brightness increase plus saturation decrease, Gaussian sigma 30.",
    "unsharp25": "Grayscale unsharp mask at Gaussian sigma 25.",
    "blue-channel": "Blue channel only, as grayscale.",
    "blue-inverted": "Blue channel only, inverted.",
    "blue-inverted-highpass2": "Inverted blue channel, Gaussian high-pass radius 2, Hard Light.",
    "yellow-reduced-inverted": "Approximate six-hue monochrome mix, yellow -100%, blue 100%, inverted.",
}


def orientation_view(width, height, orientation="upright"):
    if orientation not in ORIENTATIONS:
        raise ValueError("Unknown measured orientation.")
    mirrored = orientation.startswith("mirror-")
    angle = 0 if orientation == "upright" else int(orientation.split("-")[-1])
    matrices = {
        0: ((1, 0, 0), (0, 1, 0), (0, 0, 1)),
        90: ((0, 1, 0), (-1, 0, height), (0, 0, 1)),
        180: ((-1, 0, width), (0, -1, height), (0, 0, 1)),
        270: ((0, -1, width), (1, 0, 0), (0, 0, 1)),
    }
    matrix = np.asarray(matrices[angle], dtype=float)
    if mirrored:
        matrix = np.asarray(((-1, 0, width), (0, 1, 0), (0, 0, 1))) @ matrix
    w, h = (height, width) if angle in (90, 270) else (width, height)
    return View(
        orientation, w, h, tuple(map(tuple, matrix)), rotation=angle, mirrored=mirrored
    )


def measured_passes_for_size(width, height):
    original = orientation_view(width, height)
    passes = [
        (orientation_view(width, height, name), "unchanged") for name in ORIENTATIONS
    ]
    passes.extend((original, name) for name in CONTRASTS if name != "unchanged")
    # These exact central bands improved the three Anamorpher development cases.
    for fraction in (0.5, 0.25):
        top, bottom = (
            int(height * (0.5 - fraction / 2)),
            int(height * (0.5 + fraction / 2)),
        )
        view = View(
            f"center-band-{fraction:g}",
            width,
            bottom - top,
            ((1, 0, 0), (0, 1, top), (0, 0, 1)),
            crop=(0, top, width, bottom),
        )
        passes.extend(
            (view, name) for name in ("unchanged", "green-minus-red", "blue-minus-red")
        )
    for fraction in (0.75, 0.5):
        left, right = (
            int(width * (0.5 - fraction / 2)),
            int(width * (0.5 + fraction / 2)),
        )
        top, bottom = int(height * 0.25), int(height * 0.75)
        view = View(
            f"center-crop-{fraction:g}x0.5",
            right - left,
            bottom - top,
            ((1, 0, left), (0, 1, top), (0, 0, 1)),
            crop=(left, top, right, bottom),
        )
        passes.extend(
            (view, name) for name in ("unchanged", "green-minus-red", "blue-minus-red")
        )
    return passes


def _stretch(channel, percentiles=True):
    if not percentiles:
        return cv2.normalize(channel, None, 0, 255, cv2.NORM_MINMAX)
    low, high = (
        np.percentile(channel, (2, 98))
        if percentiles
        else (channel.min(), channel.max())
    )
    if high <= low:
        return channel.copy()
    return np.rint(
        np.clip((channel.astype(np.float32) - low) * 255 / (high - low), 0, 255)
    ).astype(np.uint8)


def _sauvola(channel, window):
    values = channel.astype(np.float64)
    mean = cv2.boxFilter(
        values, -1, (window, window), borderType=cv2.BORDER_REFLECT_101
    )
    squares = cv2.boxFilter(
        values * values, -1, (window, window), borderType=cv2.BORDER_REFLECT_101
    )
    std = np.sqrt(np.maximum(squares - mean * mean, 0))
    return np.where(values > mean * (1 + 0.2 * (std / 127.5 - 1)), 255, 0).astype(
        np.uint8
    )


def apply_measured_filter(image, name):
    if name not in CONTRASTS:
        raise ValueError(f"Unknown filter: {name}")
    if name == "unchanged":
        return image
    pixels = np.asarray(image)
    gray = cv2.cvtColor(pixels, cv2.COLOR_RGB2GRAY)
    saturation = cv2.cvtColor(pixels, cv2.COLOR_RGB2HSV)[:, :, 1]
    if name == "stretch-gray":
        result = _stretch(gray)
    elif name == "stretch-rgb":
        result = np.stack([_stretch(pixels[:, :, i]) for i in range(3)], axis=2)
    elif name == "clahe-lab":
        lab = cv2.cvtColor(pixels, cv2.COLOR_RGB2LAB)
        lab[:, :, 0] = cv2.createCLAHE(clipLimit=2, tileGridSize=(8, 8)).apply(
            lab[:, :, 0]
        )
        result = cv2.cvtColor(lab, cv2.COLOR_LAB2RGB)
    elif name in {"saturation", "saturation-inverted"}:
        result = saturation if name == "saturation" else 255 - saturation
    elif name.startswith("saturation-clahe"):
        result = cv2.createCLAHE(clipLimit=2, tileGridSize=(8, 8)).apply(saturation)
        if name.endswith("inverted"):
            result = 255 - result
    elif name == "saturation-sauvola25":
        result = _sauvola(saturation, 25)
    elif name in {"lightness-tophat31", "combined-strokes61"}:
        size = 31 if name.endswith("31") else 61
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (size, size))
        strokes = cv2.morphologyEx(gray, cv2.MORPH_TOPHAT, kernel)
        if name == "combined-strokes61":
            strokes = np.maximum(
                strokes, cv2.morphologyEx(saturation, cv2.MORPH_BLACKHAT, kernel)
            )
        result = 255 - cv2.normalize(strokes, None, 0, 255, cv2.NORM_MINMAX)
    elif "hat" in name:
        size = int(
            name.removeprefix("saturation-blackhat").removeprefix("saturation-whitehat")
        )
        operation = cv2.MORPH_TOPHAT if "whitehat" in name else cv2.MORPH_BLACKHAT
        strokes = cv2.morphologyEx(
            saturation,
            operation,
            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (size, size)),
        )
        normalized = cv2.normalize(strokes, None, 0, 255, cv2.NORM_MINMAX)
        result = normalized if operation == cv2.MORPH_TOPHAT else 255 - normalized
    elif name.startswith("saturation-minmax"):
        result = _stretch(saturation, False)
        if name.endswith("inverted"):
            result = 255 - result
    elif name in {
        "green-minus-red",
        "blue-minus-red",
        "green-red-minmax-inverted",
        "blue-red-minmax-inverted",
    }:
        channel = 1 if name.startswith("green") else 2
        result = cv2.subtract(pixels[:, :, channel], pixels[:, :, 0])
        if "minmax" in name:
            result = 255 - _stretch(result, False)
    elif name == "gamma-bright":
        result = cv2.LUT(
            pixels, np.rint(255 * (np.arange(256) / 255) ** 0.5).astype(np.uint8)
        )
    elif name == "log-rgb":
        result = cv2.LUT(
            pixels,
            np.rint(255 * np.log1p(np.arange(256) / 255) / np.log(2)).astype(np.uint8),
        )
    elif name == "inverted":
        result = 255 - pixels
    elif name == "otsu-light":
        result = cv2.threshold(
            cv2.GaussianBlur(255 - gray, (5, 5), 0),
            0,
            255,
            cv2.THRESH_BINARY + cv2.THRESH_OTSU,
        )[1]
    elif name == "sauvola101":
        result = _sauvola(gray, 101)
    elif name == "white-saliency":
        bright = np.maximum(
            gray.astype(np.int16) - cv2.GaussianBlur(gray, (0, 0), 30).astype(np.int16),
            0,
        )
        desat = np.maximum(
            cv2.GaussianBlur(saturation, (0, 0), 30).astype(np.int16)
            - saturation.astype(np.int16),
            0,
        )
        result = 255 - cv2.normalize(
            bright.astype(np.float32) + desat, None, 0, 255, cv2.NORM_MINMAX
        ).astype(np.uint8)
    elif name == "unsharp25":
        result = cv2.addWeighted(gray, 2, cv2.GaussianBlur(gray, (0, 0), 25), -1, 0)
    elif name.startswith("blue-"):
        result = image.getchannel("B")
        if name != "blue-channel":
            result = ImageOps.invert(result)
        if name.endswith("highpass2"):
            highpass = ImageChops.subtract(
                result, result.filter(ImageFilter.GaussianBlur(2)), offset=128
            )
            result = ImageChops.hard_light(result, highpass)
        return result.convert("RGB")
    else:
        # The explicitly approximate six-hue mix tested in the Photoshop trial.
        values = pixels.astype(np.float32) / 255
        hue = cv2.cvtColor(values, cv2.COLOR_RGB2HSV)[:, :, 0] / 60
        index = np.floor(hue).astype(int) % 6
        fraction = hue - np.floor(hue)
        weights = np.asarray((40, -100, 40, 60, 100, 80), dtype=np.float32) / 100
        weight = weights[index] * (1 - fraction) + weights[(index + 1) % 6] * fraction
        low, high = values.min(axis=2), values.max(axis=2)
        result = 255 - np.rint(np.clip(low + (high - low) * weight, 0, 1) * 255).astype(
            np.uint8
        )
    return Image.fromarray(result).convert("RGB")
