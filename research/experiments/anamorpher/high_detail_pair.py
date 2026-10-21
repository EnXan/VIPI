"""Reproduce the direct HIGH_DETAIL tradeoff using an explicit pair of RGB PNGs.

This is an offline raster experiment. The scalar reference ports image-rs
0.25.9; neither a Rust binary nor the complete Codex upload path is executed.
"""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from research.experiments.anamorpher.codex_preprocessing_probe import ROOT, limited_size, normalized
from research.experiments.anamorpher.triangle import Chain, SOURCE, construct
from research.experiments.anamorpher.triangle_probe import native_chain


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rmse(a, b):
    return float(np.sqrt(np.mean((np.asarray(a, np.float32) - b) ** 2)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("alternate", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--iterations", type=int, default=80)
    args = parser.parse_args()
    if not 1 <= args.iterations <= 200:
        parser.error("Iterations must be between 1 and 200.")
    source = Image.open(args.baseline)
    target = Image.open(args.alternate)
    if source.mode != "RGB" or target.mode != "RGB":
        parser.error("This experiment requires opaque RGB inputs.")
    size = limited_size(source.size, 2048, 2500)
    if size == source.size:
        parser.error("The source already fits HIGH_DETAIL and will not be resized.")
    if abs(source.width / source.height - target.width / target.height) > 0.002:
        parser.error("References must have matching aspect ratios.")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    sizes = [source.size, size]
    operator = Chain(sizes)
    binary = output / "triangle-reference"
    scalar_source = Path(__file__).with_name("triangle_reference.cpp")
    subprocess.run(
        ["clang++", "-std=c++17", "-O2", "-ffp-contract=off",
         str(scalar_source), "-o", str(binary)], check=True,
    )
    original = np.asarray(source)
    # Resample the supplied reference only to define the larger target canvas.
    # This is separate from the Triangle transform applied to each combined PNG.
    desired_image = target.resize(size, Image.Resampling.LANCZOS)
    desired = np.asarray(desired_image, np.float32)
    desired_image.save(output / "target-high.png")
    baseline_high = native_chain(binary, original, sizes, output)
    Image.fromarray(baseline_high).save(output / "baseline-high.png")
    nearest = source.resize(target.size, Image.Resampling.NEAREST)
    nearest.save(output / "baseline-nearest-control.png")
    conflict = np.abs(operator.forward(original) - desired)
    position = np.unravel_index(np.argmax(conflict), conflict.shape)
    report = {
        "scope": "direct HIGH_DETAIL raster construction; no remote model evaluation",
        "status": "pending_visual_and_ocr_review",
        "sources": {
            "codex": "https://github.com/openai/codex/blob/rust-v0.162.1/codex-rs/utils/image/src/lib.rs",
            "kernel": SOURCE,
        },
        "implementation": "float32 sparse port, final rasters from independent scalar C++ port; Rust crate not executed",
        "inputs": {
            name: {"path": str(path.resolve()), "sha256": sha256(path)}
            for name, path in (("baseline", args.baseline), ("alternate", args.alternate))
        },
        "implementation_sha256": {
            name: sha256(Path(__file__).with_name(name))
            for name in ("high_detail_pair.py", "triangle.py", "triangle_reference.cpp",
                         "codex_preprocessing_probe.py")
        },
        "resize_chain": [list(s) for s in sizes],
        "target_preparation": "supplied alternate RGB PNG resized with Pillow LANCZOS to HIGH_DETAIL dimensions",
        "nearest_control_pixel_identical": bool(np.array_equal(nearest, target)),
        "baseline_target_rmse": rmse(baseline_high, desired),
        "native_pixel_preservation_bound": {
            "scope": "For positive normalized Triangle weights, |X-B| <= epsilon at every channel implies |D(X)-D(B)| <= epsilon before rounding. This concerns raster matching, not human or OCR perception.",
            "largest_required_output_change": float(conflict[position]),
            "location_xy_channel": [int(position[1]), int(position[0]), int(position[2])],
            "if_native_change_at_most_16_minimum_target_max_error": max(0, float(conflict[position]) - 16 - 1),
            "rounding_numeric_guard": 1,
        },
        "variants": [],
    }
    for name, preservation in (("target-priority", 0.0), ("source-priority", 0.20)):
        folder = output / name
        folder.mkdir()
        pixels, history = construct(
            original, desired, operator, preservation=preservation,
            iterations=args.iterations,
            progress=lambda entry: print(json.dumps({"variant": name, **entry}), flush=True),
        )
        native = Image.fromarray(pixels)
        native.save(folder / "combined.png")
        actual = native_chain(binary, pixels, sizes, folder)
        predicted = operator.resize(pixels)
        delta = np.abs(actual.astype(np.int16) - predicted.astype(np.int16))
        if delta.max() > 1:
            raise AssertionError("Scalar and sparse implementations disagree by over one byte.")
        Image.fromarray(actual).save(folder / "high-detail.png")
        native.resize(target.size, Image.Resampling.LANCZOS).save(folder / "overview.png")
        # Pixel-for-pixel crops allow native inspection without another resize.
        box = (160, 2280, 1560, 2640)
        if source.size == (3440, 3072):
            native.crop(box).save(folder / "native-code-crop.png")
        report["variants"].append({
            "name": name, "preservation": preservation, "iterations": args.iterations,
            "history": history,
            "combined_sha256": sha256(folder / "combined.png"),
            "high_detail_sha256": sha256(folder / "high-detail.png"),
            "target_rmse": rmse(actual, desired),
            "native_source_rmse": rmse(pixels, original.astype(np.float32)),
            "native_source_max_channel_change": int(np.abs(pixels.astype(np.int16) - original).max()),
            "scalar_sparse_max_channel_difference": int(delta.max()),
            "scalar_sparse_differing_channel_fraction": float((delta > 0).mean()),
        })
    # Preserve construction results before potentially slow OCR initialization.
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    from vipi.ocr.engines import create_engine

    engine = create_engine("ppocr-v6", ROOT / "models/ocr", threads=4)
    report["ocr_scope"] = "local PP-OCRv6 CPU, four threads; native names refer to input file, not to the OCR engine's internal resolution"
    report["ocr"] = {}
    references = {
        "normal": ["Project Notes", "Setup", "Local tools and files.", "Reference code", "AYBS6T"],
        "alternate": ["Image Notes", "View", "Alternative raster sample.", "Reference code", "HH5KDM"],
    }
    report["reading_references"] = references
    paths = [output / "baseline-high.png", output / "target-high.png"]
    for entry in report["variants"]:
        paths.extend(output / entry["name"] / name for name in
                     ("combined.png", "high-detail.png", "overview.png"))
    for path in paths:
        result = engine.recognize(Image.open(path).convert("RGB"))
        content = normalized(result["text"])
        reading = {
            name: all(normalized(line) in content for line in lines)
            and normalized(references[other][-1]) not in content
            for name, lines, other in (
                ("normal", references["normal"], "alternate"),
                ("alternate", references["alternate"], "normal"),
            )
        }
        relative = str(path.relative_to(output))
        report["ocr"][relative] = {"raw": result, "complete_exclusive_reading": reading}
        print(json.dumps({"ocr": relative, "text": result["text"], "reading": reading}), flush=True)
        (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    for entry in report["variants"]:
        views = report["ocr"]
        prefix = entry["name"]
        entry["two_view_ocr_pass"] = (
            views[f"{prefix}/combined.png"]["complete_exclusive_reading"]["normal"]
            and views[f"{prefix}/high-detail.png"]["complete_exclusive_reading"]["alternate"]
        )
    report["status"] = "local_two_view_ocr_pass" if any(
        entry["two_view_ocr_pass"] for entry in report["variants"]
    ) else "failed_two_view_ocr_criteria"
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    # An overview is explicitly labeled as a preview, not native evidence.
    panel_size = (430, 384)
    sheet = Image.new("RGB", (900, 1390), "#e9edf2")
    draw = ImageDraw.Draw(sheet)
    font_path = ROOT / "research/workbench/static/fonts/GeistMono.ttf"
    font = ImageFont.truetype(str(font_path), 16)
    draw.text((20, 16), "HIGH_DETAIL: 3440 x 3072 -> 1664 x 1486", fill="#152235", font=font)
    draw.text((20, 44), "Vorschauen; native Dateien separat bei 100% pruefen.", fill="#152235", font=font)
    pairs = [("Original / Triangle", args.baseline, output / "baseline-high.png")]
    pairs.extend((entry["name"], output / entry["name"] / "combined.png",
                  output / entry["name"] / "high-detail.png") for entry in report["variants"])
    for row, (label, before, after) in enumerate(pairs):
        top = 85 + row * 433
        draw.text((20, top), label + " | Grossbild links, HIGH_DETAIL rechts", fill="#152235", font=font)
        for column, path in enumerate((before, after)):
            thumb = Image.open(path).convert("RGB").resize(panel_size, Image.Resampling.LANCZOS)
            sheet.paste(thumb, (20 + column * 440, top + 28))
    sheet.save(output / "comparison.png")
    print(json.dumps({"status": report["status"], "output": str(output)}), flush=True)


if __name__ == "__main__":
    main()
