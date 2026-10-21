"""Compare neutral fixtures under public Codex image sizing policies.

Dimensions are ported from codex-utils-image at rust-v0.162.1. Pillow BILINEAR
approximates the Rust Triangle kernel family; pixel identity with Rust is NOT
claimed. Offline OCR is separate from the manual Codex observations.
"""

# ruff: noqa: E402
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import sys

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
from vipi.ocr.engines import create_engine

UPSTREAM = (
    "https://github.com/openai/codex/blob/rust-v0.162.1/codex-rs/utils/image/src/lib.rs"
)
LOCAL_MEDIA = "https://github.com/openai/codex/blob/rust-v0.162.1/codex-rs/protocol/src/local_media.rs"


def rust_round(value):
    return math.floor(value + 0.5)


def fits(width, height, dimension, patches):
    return (
        max(width, height) <= dimension
        and math.ceil(width / 32) * math.ceil(height / 32) <= patches
    )


def limited_size(size, dimension, patches):
    """Port of prompt_image_output_dimensions_for_limits; positive inputs only."""
    width, height = size
    if min(size) < 1:
        raise ValueError("Image dimensions must be positive.")
    if fits(width, height, dimension, patches):
        return size
    scale = min(dimension / max(size), 1.0)
    width, height = (
        max(1, rust_round(width * scale)),
        max(1, rust_round(height * scale)),
    )
    if fits(width, height, dimension, patches):
        return width, height
    scale = math.sqrt(32 * 32 * patches / width / height)
    wide, high = width * scale / 32, height * scale / 32
    scale *= min(math.floor(wide) / wide, math.floor(high) / high)
    return max(1, math.floor(width * scale)), max(1, math.floor(height * scale))


def normalized(text):
    return re.sub(r"[^A-Z0-9]", "", text.upper())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixtures", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    manifest = json.loads((args.fixtures / "manifest.json").read_text())
    engine = create_engine("ppocr-v6", ROOT / "models/ocr", threads=4)
    report = {
        "source": UPSTREAM,
        "local_attachment_source": LOCAL_MEDIA,
        "sizing_implementation": "Python port of tagged Rust dimension rules",
        "raster_implementation": "Pillow BILINEAR approximation to Rust Triangle; not bit-exact Rust execution",
        "ocr": "offline PP-OCRv6 CPU, four threads; not a Codex model response",
        "codes": manifest["codes"],
        "cases": [],
    }
    for case in manifest["cases"]:
        if not case["image"].startswith("case-2/"):
            continue
        path = args.fixtures / case["image"]
        source = Image.open(path).convert("RGB")
        high = limited_size(source.size, 2048, 2500)
        original = limited_size(source.size, 6000, 10000)
        # ResizeToFit at attachment ingestion caps the longest side at 2048.
        ratio = min(1.0, 2048 / max(source.size))
        attachment_size = tuple(max(1, rust_round(v * ratio)) for v in source.size)
        attachment = source.resize(attachment_size, Image.Resampling.BILINEAR)
        reference_size = tuple(case["reference_size"])
        variants = {
            "triangle-family-high-one-step": source.resize(
                high, Image.Resampling.BILINEAR
            ),
            "triangle-family-attachment-then-high": attachment.resize(
                limited_size(attachment_size, 2048, 2500), Image.Resampling.BILINEAR
            ),
            "triangle-family-original-detail": source.resize(
                original, Image.Resampling.BILINEAR
            ),
            "bilinear-exact-quarter": source.resize(
                reference_size, Image.Resampling.BILINEAR
            ),
            "nearest-exact-quarter": source.resize(
                reference_size, Image.Resampling.NEAREST
            ),
        }
        folder = output / case["profile"]
        folder.mkdir()
        for name, image in variants.items():
            result_path = folder / f"{name}.png"
            image.save(result_path)
            result = engine.recognize(image)
            record = {
                "profile": case["profile"],
                "name": name,
                "input_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "output_sha256": hashlib.sha256(result_path.read_bytes()).hexdigest(),
                "image": str(result_path.relative_to(output)),
                "source_size": list(source.size),
                "output_size": list(image.size),
                "attachment_intermediate_size": list(attachment_size)
                if name == "triangle-family-attachment-then-high"
                else None,
                "offline_ocr": result,
                "exact_code_found": {
                    label: normalized(code) in normalized(result["text"])
                    for label, code in manifest["codes"].items()
                },
            }
            if image.size == reference_size:
                record["mean_absolute_error_from_reference"] = {
                    label: float(
                        np.abs(
                            np.asarray(image, dtype=float)
                            - np.asarray(
                                Image.open(args.fixtures / "case-2" / f"{label}.png"),
                                dtype=float,
                            )
                        ).mean()
                    )
                    for label in ("normal", "alternate")
                }
            report["cases"].append(record)
            (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
            print(
                json.dumps(
                    {
                        "profile": record["profile"],
                        "view": name,
                        "size": record["output_size"],
                        "offline_ocr_codes": record["exact_code_found"],
                    }
                ),
                flush=True,
            )


if __name__ == "__main__":
    main()
