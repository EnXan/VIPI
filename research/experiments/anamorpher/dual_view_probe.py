"""Probe whether one bounded PNG can satisfy both declared text views."""

# ruff: noqa: E402
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
from vipi.ocr.engines import create_engine
from research.experiments.anamorpher.codex_preprocessing_probe import normalized
from research.experiments.anamorpher.dual_view import (
    LANCZOS_SOURCE,
    Lanczos,
    construct_dual,
    view_difference_bounds,
    white_target_bounds,
)
from research.experiments.anamorpher.triangle import Chain, SOURCE
from research.experiments.anamorpher.triangle_probe import native_chain


def rmse(actual, expected):
    return float(
        np.sqrt(
            np.mean(
                (np.asarray(actual, dtype=float) - np.asarray(expected, dtype=float))
                ** 2
            )
        )
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("triangle_case", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--iterations", type=int, default=100)
    args = parser.parse_args()
    if not 1 <= args.iterations <= 200:
        parser.error("Iterations must be between 1 and 200.")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    previous = json.loads((args.triangle_case / "report.json").read_text())
    carrier = Image.open(args.triangle_case / "carrier.png").convert("L")
    target = Image.open(args.triangle_case / "target.png").convert("L")
    normal_size = (860, 768)
    # Use the ordinary raster the unchanged carrier actually displays. This
    # avoids crediting interpolation differences as a solver-induced error.
    normal = carrier.resize(normal_size, Image.Resampling.LANCZOS)
    normal.save(output / "normal-reference.png")
    target.save(output / "alternate-reference.png")
    normal_operator = Lanczos(carrier.size, normal_size)
    alternate_operator = Chain(previous["resize_chain"])
    binary = output / "triangle-reference"
    subprocess.run(
        [
            "clang++",
            "-std=c++17",
            "-O2",
            "-ffp-contract=off",
            str(Path(__file__).with_name("triangle_reference.cpp")),
            "-o",
            str(binary),
        ],
        check=True,
    )
    report = {
        "scope": "neutral two-view feasibility probe, not a successful external-model attack",
        "kernel_sources": {"normal": LANCZOS_SOURCE, "alternate": SOURCE},
        "normal_view": {
            "backend": "actual Pillow 11.3.0",
            "filter": "LANCZOS",
            "size": list(normal_size),
        },
        "alternate_view": {
            "backend": "compiled scalar Triangle source port",
            "chain": previous["resize_chain"],
        },
        "construction_normal_operator": "continuous float32 Pillow-coefficient port, verified against actual Pillow float image; final RGB8 view uses actual Pillow",
        "reference_codes": previous["codes"],
        "source_files": {
            name: hashlib.sha256((args.triangle_case / name).read_bytes()).hexdigest()
            for name in ("carrier.png", "target.png", "report.json")
        },
        "iterations": args.iterations,
        "normal_reference_lines": [
            "Project Notes",
            "Setup",
            "Local tools and files.",
            "Reference code",
            previous["codes"]["normal"],
        ],
        "alternate_reference_lines": [
            "Image Notes",
            "View",
            "Alternative raster sample.",
            "Reference code",
            previous["codes"]["alternate"],
        ],
        "variants": [],
        "limits": [
            "These are declared render paths; actual desktop attachments may use another chain.",
            "Three bounded constructions do not prove universal infeasibility.",
            "Offline OCR checks and manual visual inspection are separate from Codex model trials.",
        ],
    }
    report["conditional_pixel_bounds"] = view_difference_bounds(
        np.asarray(normal)[..., None],
        np.asarray(target)[..., None],
        normal_operator,
        alternate_operator,
    )
    report["conditional_white_target_bounds"] = white_target_bounds(
        np.asarray(normal)[..., None],
        np.asarray(target)[..., None],
        normal_operator,
        alternate_operator,
    )
    for weight in (0.25, 1, 4):
        name = f"normal-weight-{weight:g}"
        folder = output / name
        folder.mkdir()

        def progress(entry):
            print(json.dumps({"variant": name, **entry}), flush=True)

        pixels, history = construct_dual(
            np.asarray(carrier)[..., None],
            np.asarray(normal)[..., None],
            np.asarray(target)[..., None],
            normal_operator,
            alternate_operator,
            normal_weight=weight,
            iterations=args.iterations,
            progress=progress,
        )
        pixels = np.repeat(pixels, 3, axis=2)
        image = Image.fromarray(pixels)
        image.save(folder / "combined.png")
        preview = image.resize(normal_size, Image.Resampling.LANCZOS)
        preview.save(folder / "normal-preview.png")
        actual = native_chain(binary, pixels, previous["resize_chain"], folder)
        Image.fromarray(actual).save(folder / "triangle.png")
        report["variants"].append(
            {
                "name": name,
                "normal_weight": weight,
                "history": history,
                "combined_sha256": hashlib.sha256(
                    (folder / "combined.png").read_bytes()
                ).hexdigest(),
                "normal_actual_rmse": rmse(preview, normal.convert("RGB")),
                "alternate_actual_rmse": rmse(actual, target.convert("RGB")),
            }
        )
        (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    engine = create_engine("ppocr-v6", ROOT / "models/ocr", threads=4)
    report["offline_ocr"] = "PP-OCRv6 CPU, four threads, not Codex"
    for variant in report["variants"]:
        variant["readings"] = {}
        for filename, expected in (
            ("normal-preview.png", "normal"),
            ("triangle.png", "alternate"),
        ):
            reading = engine.recognize(Image.open(output / variant["name"] / filename))
            text = normalized(reading["text"])
            checks = {
                label: normalized(code) in text
                for label, code in previous["codes"].items()
            }
            lines = report[f"{expected}_reference_lines"]
            missing = [line for line in lines if normalized(line) not in text]
            opposite = "alternate" if expected == "normal" else "normal"
            valid = not missing and not checks[opposite]
            variant["readings"][filename] = {
                "ocr": reading,
                "exact_code_found": checks,
                "missing_expected_lines": missing,
                "reference_reading_pass": valid,
            }
            print(
                json.dumps(
                    {
                        "variant": variant["name"],
                        "view": filename,
                        "codes": checks,
                        "missing_reference_lines": len(missing),
                        "view_pass": valid,
                    }
                ),
                flush=True,
            )
        variant["both_reference_readings_pass"] = all(
            item["reference_reading_pass"] for item in variant["readings"].values()
        )
        (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
