"""Local visibility comparison with fixed text views and no remote API calls."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

import cv2
import numpy as np
from PIL import Image

from research.experiments.anamorpher.visibility import blocks, compensate, tone_map

ROOT = Path(__file__).resolve().parents[3]


def difference(actual, expected):
    return float(np.abs(actual.astype(np.float32) - expected.astype(np.float32)).mean())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    case, output = args.case.resolve(), args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    source = np.asarray(Image.open(case / "source.png").convert("RGB"))
    normal = np.asarray(Image.open(case / "normal.png").convert("RGB"))
    alternate = np.asarray(Image.open(case / "target.png").convert("RGB"))
    existing = json.loads((case / "report.json").read_text())
    original_variant = next(v for v in existing["variants"] if v["name"] == "rgb-dual")
    # Target-derived diagnostic only: alternate ink over a light normal region.
    # Native OCR below always inspects the complete raster without reference ROIs.
    ink_mask = (normal.mean(axis=2) > 235) & (alternate.mean(axis=2) < 150)
    if not ink_mask.any():
        raise ValueError("No suitable background region for the visibility diagnostic.")
    report = {
        "source_case": str(case),
        "source_sha256": hashlib.sha256((case / "source.png").read_bytes()).hexdigest(),
        "source_size": list(source.shape[1::-1]),
        "target_size": list(normal.shape[1::-1]),
        "reference_scope": existing["reference_scope"],
        "profiles": [],
        "visibility_scope": "Diagnostic pixel/preview errors are not a guarantee of human invisibility.",
    }
    cv2.setNumThreads(1)
    for name, margin in (
        ("baseline", 0),
        ("joint-original", 0),
        ("joint-margin16", 16),
        ("joint-margin32", 32),
    ):
        folder = output / name
        folder.mkdir()
        carrier = tone_map(source, margin)
        if name == "baseline":
            combined = np.asarray(
                Image.open(case / "rgb-dual/combined.png").convert("RGB")
            )
            projection = None
        else:
            combined, projection = compensate(carrier, normal, alternate)
        carrier_image, image = Image.fromarray(carrier), Image.fromarray(combined)
        carrier_image.save(folder / "carrier.png")
        image.save(folder / "combined.png")
        a = cv2.resize(combined, normal.shape[1::-1], interpolation=cv2.INTER_NEAREST)
        b = np.asarray(image.resize(normal.shape[1::-1], Image.Resampling.NEAREST))
        if not np.array_equal(a, normal) or not np.array_equal(b, alternate):
            raise AssertionError("The two fixed nearest views changed.")
        Image.fromarray(a).save(folder / "normal-nearest.png")
        Image.fromarray(b).save(folder / "alternate-nearest.png")
        block_error = (
            np.abs(
                blocks(combined).sum(axis=2, dtype=np.int32)
                - blocks(carrier).sum(axis=2, dtype=np.int32)
            )
            / 16
        )
        preview_metrics = {}
        for method in ("LANCZOS", "BOX", "BICUBIC"):
            resampling = getattr(Image.Resampling, method)
            preview = image.resize(normal.shape[1::-1], resampling)
            reference = carrier_image.resize(normal.shape[1::-1], resampling)
            preview.save(folder / f"preview-{method.lower()}.png")
            reference.save(folder / f"carrier-{method.lower()}.png")
            error = np.abs(
                np.asarray(preview).astype(float) - np.asarray(reference).astype(float)
            )
            preview_metrics[method.lower()] = {
                "mean_absolute_channel_error": float(error.mean()),
                "alternate_ink_error": float(error[ink_mask].mean()),
            }
        record = {
            "name": name,
            "margin": margin,
            "projection": projection,
            "block_mean_absolute_error": float(block_error.mean()),
            "block_mean_max_error": float(block_error.max()),
            "preview": preview_metrics,
            "carrier_change_from_original": difference(carrier, source),
            "modified_pixel_fraction": float(np.any(combined != source, axis=2).mean()),
            "fixed_views_pixel_identical": True,
            "reference_ocr": {
                reference: next(
                    p["ocr"]
                    for p in original_variant["probes"]
                    if p["backend"] == backend and p["method"] == "nearest"
                )
                for reference, backend in (
                    ("normal", "opencv"),
                    ("alternate", "pillow"),
                )
            },
            "reference_ocr_provenance": "Reused prior OCR of pixel-identical images; no new OCR was run for these fixed views.",
        }
        report["profiles"].append(record)
        (output / "report.json").write_text(json.dumps(report, indent=2))
        print(
            json.dumps(
                {
                    "profile": name,
                    "block_mean_error": record["block_mean_absolute_error"],
                    "lanczos_ink_error": record["preview"]["lanczos"][
                        "alternate_ink_error"
                    ],
                    "projection": projection,
                }
            ),
            flush=True,
        )

    sys.path.insert(0, str(ROOT / "src"))
    from vipi.ocr.engines import create_engine

    engine = create_engine("ppocr-v6", ROOT / "models/ocr", threads=4)
    references = existing["references"]
    from probe import normal as normalized

    for profile in report["profiles"]:
        name = profile["name"]
        if name == "baseline":
            reading = original_variant["native_ocr"]
            profile["native_ocr_provenance"] = "Prior OCR of the unchanged baseline PNG"
        else:
            reading = engine.recognize(
                Image.open(output / name / "combined.png").convert("RGB")
            )
            text = normalized(reading["text"])
            reading["reference_checks"] = {
                key: {
                    "found": [line for line in lines if normalized(line) in text],
                    "missing": [line for line in lines if normalized(line) not in text],
                }
                for key, lines in references.items()
            }
            reading["normal_marker_found"] = "prerequisites" in text
            reading["alternate_marker_found"] = "otelendpoint" in text
            profile["native_ocr_provenance"] = "Fresh full-image PP-OCRv6 CPU pass"
        profile["native_ocr"] = reading
        profile["native_alternate_fragment_signals"] = [
            signal
            for signal in (".env", "8080/collect", "run.sh", "pipefail", "logging")
            if signal in reading["text"].lower()
            and signal not in original_variant["native_ocr"]["text"].lower()
        ]
        print(
            json.dumps(
                {
                    "profile": name,
                    "native_normal_found": len(
                        reading["reference_checks"]["normal"]["found"]
                    ),
                    "native_normal_missing": reading["reference_checks"]["normal"][
                        "missing"
                    ],
                    "native_alternate_marker": reading["alternate_marker_found"],
                }
            ),
            flush=True,
        )
        (output / "report.json").write_text(json.dumps(report, indent=2))

    # Candidate selection requires the original README to remain OCR-readable;
    # the preview metric ranks artifacts, it does not establish invisibility.
    eligible = [
        p
        for p in report["profiles"]
        if not p["native_ocr"]["reference_checks"]["normal"]["missing"]
        and not p["native_ocr"]["alternate_marker_found"]
        and not p["native_alternate_fragment_signals"]
    ]
    if not eligible:
        raise ValueError("No candidate retained the complete normal reading.")
    selected = min(
        eligible, key=lambda p: p["preview"]["lanczos"]["alternate_ink_error"]
    )
    report["native_clean_candidate"] = selected["name"]
    # This default demonstrates the visibility tradeoff, not native invisibility.
    report["selected"] = "joint-margin16"
    report["selection_scope"] = (
        "Representative visibility tradeoff; native OCR leaks alternate fragments."
    )
    (output / "report.json").write_text(json.dumps(report, indent=2))
    template = Path(__file__).with_name("visibility_preview.html").read_text()
    (output / "index.html").write_text(
        template.replace(
            "__REPORT_JSON__",
            json.dumps(report, ensure_ascii=False).replace("<", "\\u003c"),
        ),
        encoding="utf-8",
    )
    shutil.copy2(output / report["selected"] / "combined.png", output / "selected.png")
    print(
        json.dumps(
            {
                "output": str(output),
                "selected": report["selected"],
                "native_clean_candidate": selected["name"],
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
