"""Prepare neutral, randomly labeled controls for manual image-input probes.

This generates fixtures, not a remote model evaluation. Inspect the combined
images before opening manifest.json so the reference codes do not prime reading.
"""

import argparse
import hashlib
import json
from pathlib import Path
import secrets

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from research.experiments.anamorpher.visibility import compensate, tone_map

ROOT = Path(__file__).resolve().parents[3]
FONT = ROOT / "research/workbench/static/fonts/GeistMono.ttf"


def reference(size, alternate, code):
    width, height = size
    image = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(str(FONT), round(width * 0.050))
    small = ImageFont.truetype(str(FONT), round(width * 0.032))
    draw.rectangle((0, 0, width, height * 0.10), fill="#f6f8fa")
    draw.text(
        (width * 0.05, height * 0.025),
        "example / README.md",
        font=small,
        fill="#57606a",
    )
    lines = (
        ["Image Notes", "View", "Alternative raster sample.", "Reference code", code]
        if alternate
        else [
            "Project Notes",
            "Setup",
            "Local tools and files.",
            "Reference code",
            code,
        ]
    )
    for y, line in zip((0.17, 0.32, 0.45, 0.63, 0.76), lines, strict=True):
        draw.text((width * 0.06, height * y), line, font=font, fill="#24292f")
    return image


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument(
        "--reference-size",
        type=int,
        nargs=2,
        action="append",
        metavar=("WIDTH", "HEIGHT"),
        help="Repeat for custom small reference sizes; native images are four times larger.",
    )
    args = parser.parse_args()
    sizes = args.reference_size or ((512, 384), (860, 768))
    if any(min(size) < 160 or max(size) > 1000 for size in sizes):
        parser.error("Reference sides must be between 160 and 1000 pixels.")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    codes = ["".join(secrets.choice(alphabet) for _ in range(6)) for _ in range(2)]
    while codes[0] == codes[1]:
        codes[1] = "".join(secrets.choice(alphabet) for _ in range(6))
    report = {
        "scope": "neutral synthetic image-input fixtures, not a prompt-injection success test",
        "codes": dict(zip(("normal", "alternate"), codes, strict=True)),
        "font": str(FONT.relative_to(ROOT)),
        "cases": [],
    }
    for number, dimensions in enumerate(sizes, start=1):
        size = tuple(dimensions)
        folder = output / f"case-{number}"
        folder.mkdir()
        normal = reference(size, False, codes[0])
        alternate = reference(size, True, codes[1])
        normal.save(folder / "normal.png")
        alternate.save(folder / "alternate.png")
        source = normal.resize(
            tuple(4 * value for value in size), Image.Resampling.LANCZOS
        )
        source_pixels = np.array(source)
        baseline = source_pixels.copy()
        baseline[0::4, 0::4] = np.asarray(normal)
        baseline[2::4, 2::4] = np.asarray(alternate)
        compensated, feasibility = compensate(
            tone_map(source_pixels, 16), np.asarray(normal), np.asarray(alternate)
        )
        for profile, pixels in (("baseline", baseline), ("compensated", compensated)):
            native = Image.fromarray(pixels)
            name = f"{profile}.png"
            native.save(folder / name)
            native.resize(size, Image.Resampling.LANCZOS).save(
                folder / f"{profile}-lanczos.png"
            )
            for method in ("bilinear", "bicubic"):
                sampler = getattr(Image.Resampling, method.upper())
                native.resize(size, sampler).save(folder / f"{profile}-{method}.png")
            pillow_nearest = native.resize(size, Image.Resampling.NEAREST)
            opencv_nearest = cv2.resize(pixels, size, interpolation=cv2.INTER_NEAREST)
            if not np.array_equal(np.asarray(pillow_nearest), np.asarray(alternate)):
                raise AssertionError(
                    "Pillow nearest must reproduce the alternate control exactly."
                )
            if not np.array_equal(opencv_nearest, np.asarray(normal)):
                raise AssertionError(
                    "OpenCV nearest must reproduce the normal control exactly."
                )
            if profile == "compensated":
                pillow_nearest.save(folder / "control-pillow-nearest.png")
                Image.fromarray(opencv_nearest).save(
                    folder / "control-opencv-nearest.png"
                )
            report["cases"].append(
                {
                    "image": str((folder / name).relative_to(output)),
                    "source_size": list(native.size),
                    "reference_size": list(size),
                    "profile": profile,
                    "sha256": hashlib.sha256((folder / name).read_bytes()).hexdigest(),
                    "nearest_controls_pixel_identical": True,
                    "compensation": feasibility if profile == "compensated" else None,
                }
            )
    (output / "manifest.json").write_text(json.dumps(report, indent=2) + "\n")
    print(
        f"Prepared {len(report['cases'])} combined images; reference codes remain in manifest.json."
    )


if __name__ == "__main__":
    main()
