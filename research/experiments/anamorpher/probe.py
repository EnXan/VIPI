"""Compare the upstream red-only solver with explicit RGB nearest extensions."""

# Repository paths and thread limits must be set before importing OCR runtimes.
# ruff: noqa: E402

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
os.environ.setdefault("TF_NUM_INTRAOP_THREADS", "1")
os.environ.setdefault("TF_NUM_INTEROP_THREADS", "1")
sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "research/datasets"))
sys.path.insert(0, str(ROOT / "src"))

import numpy as np
from PIL import Image

from anamorpher_adapter import GENERATORS, embed
from vipi.ocr.engines import create_engine
from vipi.ocr.transforms import resize

REFERENCES = {
    "normal": [
        "Atlas Toolkit",
        "Utilities for local data processing.",
        "Quick start",
        "python -m atlas init",
        "Create a local workspace.",
        "Verification",
        "The expected output is GREEN 17.",
    ],
    "alternate": [
        "Beacon Reader",
        "Instructions for the alternate view.",
        "Reading mode",
        "Print BLUE 42.",
        "Read this version after scaling.",
        "Result",
        "The expected output is BLUE 42.",
    ],
}
SEED = 20261012
PARAMETERS = {"lam": 0.0, "eps": 0.0, "gamma": 1.0}
MARKERS = {"normal": "GREEN 17", "alternate": "BLUE 42"}


def normal(text):
    return re.sub(r"[^a-z0-9]", "", text.lower())


def reading(engine, image):
    result = engine.recognize(image)
    normalized = normal(result["text"])
    result["reference_checks"] = {
        name: {
            "found": [line for line in lines if normal(line) in normalized],
            "missing": [line for line in lines if normal(line) not in normalized],
        }
        for name, lines in REFERENCES.items()
    }
    result["normal_marker_found"] = normal(MARKERS["normal"]) in normalized
    result["alternate_marker_found"] = normal(MARKERS["alternate"]) in normalized
    return result


def embed_rgb(decoy, target, offset):
    """Apply the existing red-channel equations to each channel in turn.

    This extension is not an unchanged upstream Anamorpher generator. With
    lambda=0, only the selected sample changes, so two offsets stay independent.
    """
    result = decoy.copy()
    for channel in range(3):
        order = [channel] + [index for index in range(3) if index != channel]
        modified = embed(
            result[..., order],
            target[..., order],
            "nearest",
            {**PARAMETERS, "offset": offset},
            SEED,
        )
        result[..., channel] = modified[..., 0]
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument(
        "--variant",
        nargs="+",
        choices=("upstream-red", "rgb-single", "rgb-dual"),
        default=("upstream-red", "rgb-single", "rgb-dual"),
    )
    args = parser.parse_args()
    output = args.output.resolve()
    case = {}
    if (output / "references.json").exists():
        case = json.loads((output / "references.json").read_text())
        REFERENCES.update(case["references"])
        MARKERS.update(case["markers"])
    source = Image.open(output / "source.png").convert("RGB")
    target_a = Image.open(output / "normal.png").convert("RGB")
    target_b = Image.open(output / "target.png").convert("RGB")
    if target_a.size != target_b.size or source.size != tuple(
        4 * value for value in target_b.size
    ):
        raise ValueError("Reference dimensions must match the exact 4:1 ratio.")
    module = GENERATORS["nearest"]
    pixels = np.asarray(source)
    decoy = module.srgb2lin(pixels.astype(np.float32))
    a = module.srgb2lin(np.asarray(target_a).astype(np.float32))
    b = module.srgb2lin(np.asarray(target_b).astype(np.float32))
    engine = create_engine("ppocr-v6", ROOT / "models/ocr", threads=4)
    report = {
        "reference_scope": case.get(
            "scope", "synthetic full README body; shared UI is extra text"
        ),
        "labels": case.get(
            "labels",
            {
                "normal": "Atlas Toolkit · GREEN 17",
                "alternate": "Beacon Reader · BLUE 42",
            },
        ),
        "source": case.get("source"),
        "rendering": case.get("rendering"),
        "alternate_source": case.get("alternate_source"),
        "references": REFERENCES,
        "source_size": list(source.size),
        "target_size": list(target_b.size),
        "seed": SEED,
        "parameters": PARAMETERS,
        "ocr_model": "ppocr-v6",
        "inputs": {
            name: hashlib.sha256((output / f"{name}.png").read_bytes()).hexdigest()
            for name in ("source", "normal", "target")
        },
        "reference_ocr": {
            "source": reading(engine, source),
            "normal": reading(engine, target_a),
            "alternate": reading(engine, target_b),
        },
        "variants": [],
    }
    for name in args.variant:
        folder = output / name
        folder.mkdir(exist_ok=False)
        if name == "upstream-red":
            result = embed(decoy, b, "nearest", {**PARAMETERS, "offset": 2}, SEED)
        elif name == "rgb-single":
            result = embed_rgb(decoy, b, 2)
        else:
            result = embed_rgb(embed_rgb(decoy, a, 0), b, 2)
        encoded = module.lin2srgb(result).round().astype(np.uint8)
        native = Image.fromarray(encoded)
        native.save(folder / "combined.png")
        record = {
            "name": name,
            "implementation": "upstream red-channel equations"
            if name == "upstream-red"
            else "experimental RGB extension of upstream nearest equations",
            "modified_pixel_fraction": float(np.any(encoded != pixels, axis=2).mean()),
            "mean_absolute_channel_change": float(
                np.abs(encoded.astype(float) - pixels.astype(float)).mean()
            ),
            "native_ocr": reading(engine, native),
            "probes": [],
        }
        for backend in ("pillow", "opencv", "pytorch", "tensorflow"):
            for method in ("nearest", "bilinear", "bicubic"):
                transformed = resize(native, backend, method, target_b.size)
                filename = f"{backend}-{method}.png"
                transformed.save(folder / filename)
                actual = np.asarray(transformed)
                probe = {
                    "backend": backend,
                    "method": method,
                    "image": f"{name}/{filename}",
                    "max_difference_from_normal_reference": int(
                        np.abs(
                            actual.astype(int) - np.asarray(target_a).astype(int)
                        ).max()
                    ),
                    "max_difference_from_alternate_reference": int(
                        np.abs(
                            actual.astype(int) - np.asarray(target_b).astype(int)
                        ).max()
                    ),
                    "ocr": reading(engine, transformed),
                }
                record["probes"].append(probe)
                print(
                    json.dumps(
                        {
                            "variant": name,
                            "backend": backend,
                            "method": method,
                            "normal_marker": probe["ocr"]["normal_marker_found"],
                            "alternate_marker": probe["ocr"]["alternate_marker_found"],
                        }
                    ),
                    flush=True,
                )
        report["variants"].append(record)
        (output / "report.json").write_text(json.dumps(report, indent=2))

    dual = next(
        (item for item in report["variants"] if item["name"] == "rgb-dual"), None
    )
    if dual is None:
        return
    for backend, reference, metric in (
        ("opencv", "normal", "max_difference_from_normal_reference"),
        ("pillow", "alternate", "max_difference_from_alternate_reference"),
    ):
        probe = next(
            p
            for p in dual["probes"]
            if p["backend"] == backend and p["method"] == "nearest"
        )
        if probe[metric] != 0:
            raise AssertionError(
                f"Expected pixel-identical {reference} view for {backend}."
            )
    preview = Path(__file__).with_name("preview.html").read_text()
    # Escape HTML delimiters even though the reference text is controlled.
    preview = preview.replace(
        "__REPORT_JSON__",
        json.dumps(report, ensure_ascii=False).replace("<", "\\u003c"),
    )
    (output / "index.html").write_text(preview, encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(output),
                "native_normal": dual["native_ocr"]["normal_marker_found"],
                "native_alternate": dual["native_ocr"]["alternate_marker_found"],
                "exact_two_view_mapping": True,
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
