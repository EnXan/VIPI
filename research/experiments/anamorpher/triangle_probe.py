"""Construct neutral target images for a declared Triangle resize chain.

Records both native and scaled readings. A readable scaled target alone is not
proof of hidden text or a native-to-alternative switch in an external model.
"""

# ruff: noqa: E402
import argparse
import hashlib
import json
from pathlib import Path
import secrets
import subprocess
import sys

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
from vipi.ocr.engines import create_engine
from research.experiments.anamorpher.codex_preprocessing_probe import limited_size, normalized, rust_round
from research.experiments.anamorpher.prepare_codex_probe import reference
from research.experiments.anamorpher.triangle import Chain, SOURCE, construct


def native_chain(binary, pixels, sizes, folder):
    source = pixels
    for index, (before, after) in enumerate(zip(sizes, sizes[1:])):
        input_path = folder / f"verify-{index}-input.raw"
        output_path = folder / f"verify-{index}-output.raw"
        source.tofile(input_path)
        subprocess.run(
            [
                str(binary),
                str(input_path),
                str(output_path),
                *map(str, before),
                *map(str, after),
            ],
            check=True,
        )
        source = np.fromfile(output_path, dtype=np.uint8).reshape(after[1], after[0], 3)
        input_path.unlink()
        output_path.unlink()
    return source


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixtures", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--iterations", type=int, default=80)
    args = parser.parse_args()
    if not 1 <= args.iterations <= 200:
        parser.error("Iterations must be between 1 and 200.")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    manifest = json.loads((args.fixtures / "manifest.json").read_text())
    normal = Image.open(args.fixtures / "case-2/normal.png").convert("L")
    source_size = (3440, 3072)
    ratio = 2048 / max(source_size)
    attachment_size = tuple(rust_round(value * ratio) for value in source_size)
    target_size = limited_size(attachment_size, 2048, 2500)
    sizes = [source_size, attachment_size, target_size]
    operator = Chain(sizes)
    code = "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(6))
    while code == manifest["codes"]["normal"]:
        code = "".join(
            secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(6)
        )
    target = reference(target_size, True, code).convert("L")
    carrier = normal.resize(source_size, Image.Resampling.LANCZOS)
    carrier.convert("RGB").save(output / "carrier.png")
    target.convert("RGB").save(output / "target.png")
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
        "scope": "neutral synthetic references, source-based Triangle construction",
        "kernel_source": SOURCE,
        "codex_lock": "https://github.com/openai/codex/blob/rust-v0.162.1/codex-rs/Cargo.lock",
        "kernel_implementation": "float32 Python/SciPy port, cross-checked against independent compiled scalar C++ port; Rust crate not executed",
        "resize_chain": [list(size) for size in sizes],
        "chain_scope": "declared attachment-cap then high-detail hypothesis; not confirmed desktop upload internals",
        "construction": "bounded least squares against the Triangle chain; no model in the construction loop",
        "codes": {"normal": manifest["codes"]["normal"], "alternate": code},
        "iterations": args.iterations,
        "variants": [],
    }
    source_pixels = np.asarray(carrier)[..., None]
    target_pixels = np.asarray(target)[..., None]
    for name, preservation in (("triangle-target", 0.0), ("triangle-preserve", 0.08)):
        folder = output / name
        folder.mkdir()

        def progress(entry):
            print(json.dumps({"variant": name, **entry}), flush=True)

        pixels, history = construct(
            source_pixels,
            target_pixels,
            operator,
            preservation=preservation,
            iterations=args.iterations,
            progress=progress,
        )
        pixels = np.repeat(pixels, 3, axis=2)
        native = Image.fromarray(pixels)
        native.save(folder / "combined.png")
        actual = native_chain(binary, pixels, sizes, folder)
        predicted = operator.resize(pixels)
        difference = np.abs(actual.astype(int) - predicted.astype(int))
        if difference.max() > 1:
            raise AssertionError(
                "Native scalar and sparse Triangle differ by more than one byte."
            )
        Image.fromarray(actual).save(folder / "triangle.png")
        native.resize(normal.size, Image.Resampling.LANCZOS).save(
            folder / "lanczos-preview.png"
        )
        report["variants"].append(
            {
                "name": name,
                "preservation": preservation,
                "history": history,
                "combined_sha256": hashlib.sha256(
                    (folder / "combined.png").read_bytes()
                ).hexdigest(),
                "scalar_sparse_max_byte_difference": int(difference.max()),
                "scalar_sparse_differing_byte_fraction": float((difference > 0).mean()),
                "actual_triangle_target_rmse": float(
                    np.sqrt(
                        np.mean(
                            (
                                actual.astype(float)
                                - np.asarray(target.convert("RGB"), dtype=float)
                            )
                            ** 2
                        )
                    )
                ),
                "native_carrier_rmse": float(
                    np.sqrt(
                        np.mean(
                            (
                                pixels.astype(float)
                                - np.asarray(carrier.convert("RGB"), dtype=float)
                            )
                            ** 2
                        )
                    )
                ),
            }
        )
        (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    engine = create_engine("ppocr-v6", ROOT / "models/ocr", threads=4)
    report["offline_ocr_model"] = "PP-OCRv6 CPU, four threads; not Codex"
    for variant in report["variants"]:
        variant["readings"] = {}
        for filename in ("combined.png", "triangle.png", "lanczos-preview.png"):
            result = engine.recognize(Image.open(output / variant["name"] / filename))
            checks = {
                label: normalized(code) in normalized(result["text"])
                for label, code in report["codes"].items()
            }
            variant["readings"][filename] = {"ocr": result, "exact_code_found": checks}
            print(
                json.dumps(
                    {
                        "variant": variant["name"],
                        "view": filename,
                        "offline_ocr_codes": checks,
                    }
                ),
                flush=True,
            )
        (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
