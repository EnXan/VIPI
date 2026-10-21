"""Make a two-view RGB PNG from normal, alternate, and blank references."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess

import numpy as np
from PIL import Image

from research.experiments.anamorpher.codex_preprocessing_probe import limited_size
from research.experiments.anamorpher.triangle import Triangle, construct, rgb8
from research.experiments.anamorpher.triangle_probe import native_chain


def encode_color(normal, alternate, blank, *, shift=43, amplitude=43,
                 contrast=8, carrier="outside", ink_range=220,
                 shared_contrast=None, iterations=30):
    """Put shared colors in pixel means and normal letters in fine texture."""
    if normal.shape != alternate.shape or normal.shape != blank.shape:
        raise ValueError("All three references need identical geometry.")
    if normal.ndim != 3 or normal.shape[2] != 3:
        raise ValueError("References must be RGB arrays.")
    height, width, _ = normal.shape
    if height % 2 or width % 2:
        raise ValueError("The source dimensions must be even.")
    normal_l = np.asarray(Image.fromarray(normal).convert("L"), dtype=np.float32)
    alternate_l = np.asarray(Image.fromarray(alternate).convert("L"), dtype=np.float32)
    blank_l = np.asarray(Image.fromarray(blank).convert("L"), dtype=np.float32)
    normal_ink = np.clip((blank_l - normal_l) / ink_range, 0, 1)
    alternate_ink = np.clip((blank_l - alternate_l) / ink_range, 0, 1)
    base = np.maximum(blank.astype(np.float32) - shift, 0)
    if shared_contrast is None:
        mean = base - contrast * alternate_ink[..., None]
        source_carrier = normal_ink
    else:
        shared_ink = np.minimum(normal_ink, alternate_ink)
        alternate_only = alternate_ink - shared_ink
        source_carrier = normal_ink - shared_ink
        mean = (base - shared_contrast * shared_ink[..., None]
                - contrast * alternate_only[..., None])
    y, x = np.indices((height, width), sparse=True)
    checker = 2 * ((x + y) % 2) - 1
    carrier_mask = source_carrier if carrier in ("inside", "dots") else 1 - normal_ink
    if carrier == "dots":
        wave = np.where((x % 2 == 0) & (y % 2 == 0), -3, 1)
    else:
        wave = checker
    initial = rgb8(mean + amplitude * carrier_mask[..., None] * wave[..., None])
    operator = Triangle((width, height), (width // 2, height // 2))
    desired = operator.resize(mean)
    pixels, history = construct(initial, desired, operator,
                                preservation=0, iterations=iterations)
    return pixels, desired, history


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("normal", type=Path)
    parser.add_argument("alternate", type=Path)
    parser.add_argument("blank", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--shift", type=int, default=43)
    parser.add_argument("--amplitude", type=int, default=43)
    parser.add_argument("--contrast", type=int, default=8)
    parser.add_argument("--carrier", choices=("outside", "inside", "dots"), default="outside")
    parser.add_argument("--ink-range", type=int, default=220)
    parser.add_argument("--shared-contrast", type=int)
    args = parser.parse_args()
    if not 0 <= args.shift <= 100 or not 1 <= args.amplitude <= 100:
        parser.error("Use 0 <= shift <= 100 and 1 <= amplitude <= 100.")
    if not 1 <= args.contrast <= 32:
        parser.error("Contrast must be between 1 and 32.")
    if not 1 <= args.ink_range <= 255:
        parser.error("Ink range must be between 1 and 255.")
    if args.shared_contrast is not None and not 1 <= args.shared_contrast <= 180:
        parser.error("Shared contrast must be between 1 and 180.")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    inputs = [args.normal, args.alternate, args.blank]
    images = [Image.open(path).convert("RGB") for path in inputs]
    size = images[0].size
    if any(image.size != size for image in images):
        parser.error("All three references need identical geometry.")
    high_size = limited_size(size, 2048, 2500)
    if high_size != (size[0] // 2, size[1] // 2):
        parser.error("Codex HIGH_DETAIL must be exactly half the reference size.")
    resized = [np.asarray(image) for image in images]
    pixels, desired, history = encode_color(
        *resized, shift=args.shift, amplitude=args.amplitude,
        contrast=args.contrast, carrier=args.carrier,
        ink_range=args.ink_range, shared_contrast=args.shared_contrast,
    )
    Image.fromarray(pixels).save(output / "combined.png")
    Image.fromarray(desired).save(output / "target-color.png")
    binary = output / "triangle-reference"
    subprocess.run([
        "clang++", "-std=c++17", "-O2", "-ffp-contract=off",
        str(Path(__file__).with_name("triangle_reference.cpp")), "-o", str(binary),
    ], check=True)
    high = native_chain(binary, pixels, [size, high_size], output)
    sparse = Triangle(size, high_size).resize(pixels)
    if not np.array_equal(high, sparse):
        raise AssertionError("C++ and sparse RGB Triangle results disagree.")
    Image.fromarray(high).save(output / "high-detail.png")
    error = high.astype(np.int16) - desired.astype(np.int16)
    report = {
        "status": "raster_verified_pending_view_observation",
        "source_size": size,
        "high_detail_size": high_size,
        "method": "Shared reference colors in RGB means; native-only letters in fine texture; alternate-only letters in the mean.",
        "inputs": {name: {"path": str(path.resolve()), "sha256": digest(path)}
                   for name, path in zip(("normal", "alternate", "blank"), inputs)},
        "shift": args.shift,
        "amplitude": args.amplitude,
        "contrast": args.contrast,
        "carrier": args.carrier,
        "ink_range": args.ink_range,
        "shared_contrast": args.shared_contrast,
        "history": history,
        "scalar_sparse_pixel_identical": True,
        "target_max_channel_error": int(np.abs(error).max()),
        "target_rmse": float(np.sqrt(np.mean(error.astype(np.float32) ** 2))),
        "combined_sha256": digest(output / "combined.png"),
        "high_detail_sha256": digest(output / "high-detail.png"),
    }
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"output": str(output),
                      "max_error": report["target_max_channel_error"],
                      "rmse": report["target_rmse"]}), flush=True)


if __name__ == "__main__":
    main()
