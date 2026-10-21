"""Encode two references in texture and mean intensity for direct HIGH_DETAIL.

The large view requires native pixel display. Its palette is intentionally
changed to a gray halftone. The second view has deliberately low contrast.
"""

import argparse
import base64
import hashlib
import json
from pathlib import Path
import subprocess

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from research.experiments.anamorpher.codex_preprocessing_probe import ROOT, limited_size
from research.experiments.anamorpher.triangle import Triangle, construct, rgb8
from research.experiments.anamorpher.triangle_probe import native_chain


def encode(normal, alternate, *, contrast=8, amplitude=110, background=128,
           iterations=30):
    """Store normal shapes in checkerboard amplitude, alternate in pixel means."""
    if normal.shape != alternate.shape or normal.ndim != 2:
        raise ValueError("Expected two equal-sized grayscale arrays.")
    height, width = normal.shape
    if width % 2 or height % 2:
        raise ValueError("The construction needs even source dimensions.")
    if not 1 <= contrast <= 32 or not 0 < amplitude <= 110:
        raise ValueError("Contrast and amplitude must be in their supported ranges.")
    if not 0 <= background <= 255 or background + amplitude > 255 \
            or background - contrast - amplitude < 0:
        raise ValueError("Background, contrast and amplitude must preserve RGB8 headroom.")
    normal_ink = np.clip((255 - normal.astype(np.float32)) / 220, 0, 1)
    alternate_ink = np.clip((255 - alternate.astype(np.float32)) / 220, 0, 1)
    operator = Triangle((width, height), (width // 2, height // 2))
    mean = background - contrast * alternate_ink
    y, x = np.indices(normal.shape, sparse=True)
    checker = 2 * ((x + y) % 2) - 1
    initial = rgb8(mean + amplitude * (1 - normal_ink) * checker)
    desired = operator.resize(mean[..., None])
    pixels, history = construct(
        initial[..., None], desired, operator,
        preservation=0, iterations=iterations,
    )
    return pixels[..., 0], desired[..., 0], history


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("normal", type=Path)
    parser.add_argument("alternate", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-stride", type=int, default=1,
                        help="Use 4 for this fixture's OpenCV-nearest normal layer; otherwise 1.")
    parser.add_argument("--contrast", type=int, default=8)
    parser.add_argument("--background", type=int, default=128)
    parser.add_argument("--amplitude", type=int, default=110)
    args = parser.parse_args()
    if args.source_stride < 1:
        parser.error("Source stride must be positive.")
    size = (3328, 2972)
    target_size = limited_size(size, 2048, 2500)
    if target_size != (1664, 1486):
        raise AssertionError("The declared HIGH_DETAIL geometry changed.")
    source = Image.open(args.normal).convert("RGB")
    alternate = Image.open(args.alternate).convert("RGB")
    # For the supplied baseline, (0,0) in each 4x4 block is its normal layer.
    normal = Image.fromarray(np.asarray(source)[::args.source_stride, ::args.source_stride])
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    normal.save(output / "normal-reference.png")
    alternate.save(output / "alternate-reference.png")
    normal_gray = np.asarray(normal.convert("L").resize(size, Image.Resampling.LANCZOS))
    alternate_gray = np.asarray(alternate.convert("L").resize(size, Image.Resampling.LANCZOS))
    pixels, desired, history = encode(
        normal_gray, alternate_gray, contrast=args.contrast,
        background=args.background, amplitude=args.amplitude,
    )
    combined = Image.fromarray(pixels).convert("RGB")
    combined.save(output / "combined.png")
    Image.fromarray(desired).convert("RGB").save(output / "target-gray.png")
    binary = output / "triangle-reference"
    subprocess.run(
        ["clang++", "-std=c++17", "-O2", "-ffp-contract=off",
         str(Path(__file__).with_name("triangle_reference.cpp")), "-o", str(binary)],
        check=True,
    )
    actual = native_chain(binary, np.asarray(combined), [size, target_size], output)
    predicted = Triangle(size, target_size).resize(pixels[..., None])[..., 0]
    if not np.array_equal(actual[..., 0], predicted):
        raise AssertionError("The exact 2:1 scalar and sparse paths disagree.")
    high = Image.fromarray(actual)
    high.save(output / "high-detail.png")
    error = actual[..., 0].astype(float) - desired
    report = {
        "status": "raster_verified_pending_view_observation",
        "method": "normal reference in checkerboard amplitude; alternate in mean intensity; projected correction against antialiased Triangle",
        "inputs": {name: {"path": str(path.resolve()), "sha256": sha256(path)}
                   for name, path in (("normal", args.normal), ("alternate", args.alternate))},
        "source_stride": args.source_stride,
        "source_stride_origin": [0, 0],
        "reference_preparation": "grayscale, LANCZOS resize, ink=(255-gray)/220 clipped to [0,1]; palette is not preserved",
        "source_size": list(size), "high_detail_size": list(target_size),
        "original_detail_size": list(limited_size(size, 6000, 10000)),
        "contrast": args.contrast, "mean_background": args.background,
        "checker_amplitude": args.amplitude,
        "iterations": 30, "history": history,
        "scalar_sparse_pixel_identical": True,
        "target_max_channel_error": int(np.abs(error).max()),
        "target_rmse": float(np.sqrt(np.mean(error**2))),
        "combined_sha256": sha256(output / "combined.png"),
        "high_detail_sha256": sha256(output / "high-detail.png"),
        "implementation": "image-rs 0.25.9 float32 formula; independently compiled C++ reference. Rust crate not executed.",
        "implementation_sha256": {name: sha256(Path(__file__).with_name(name)) for name in
                                  ("frequency_pair.py", "triangle.py", "triangle_reference.cpp")},
        "conditions": ["Native view: one image pixel per physical display pixel, or integer nearest enlargement.",
                       "High view: direct 3328x2972 to 1664x1486 Triangle; no additional contrast adjustment.",
                       "Browser fit-to-window can erase the normal view before inspection.",
                       "Lossless opaque PNG. Other resize chains are not covered."],
    }
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    box = (150, 2170, 1550, 2560)
    native_crop = combined.crop(box)
    high_crop = high.crop(tuple(value // 2 for value in box))
    native_crop.save(output / "native-code.png")
    high_crop.save(output / "high-code.png")
    combined.crop((150, 465, 1850, 760)).save(output / "native-title.png")
    comparison = Image.new("RGB", (1440, 770), "#edf0f5")
    draw = ImageDraw.Draw(comparison)
    font = ImageFont.truetype(str(ROOT / "research/workbench/static/fonts/GeistMono.ttf"), 21)
    draw.text((20, 18), "Original: nativer Ausschnitt (keine Skalierung)", font=font, fill="#142135")
    comparison.paste(native_crop, (20, 54))
    draw.text((20, 477), "Nach HIGH_DETAIL: derselbe Bereich, 2:1 Triangle", font=font, fill="#142135")
    comparison.paste(high_crop, (20, 515))
    comparison.save(output / "comparison.png")
    template = Path(__file__).with_name("frequency_preview.html").read_text()
    data = base64.b64encode((output / "combined.png").read_bytes()).decode("ascii")
    (output / "index.html").write_text(template.replace("__IMAGE_DATA__", "data:image/png;base64," + data))
    print(json.dumps({"output": str(output), "max_error": report["target_max_channel_error"],
                      "rmse": report["target_rmse"]}), flush=True)


if __name__ == "__main__":
    main()
