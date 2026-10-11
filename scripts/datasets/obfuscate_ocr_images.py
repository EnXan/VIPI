#!/usr/bin/env python3
"""Apply deterministic whole-image degradations to 15% of the OCR catalog."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import math
import random
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from import_mm_safetybench import write_json_atomic


ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "datasets/catalog/ocr"
OUTPUT = ROOT / "datasets/derived/ocr_obfuscation/v1"
MANIFEST = CATALOG / "ocr_obfuscation_manifest.json"
METHODS = ("gaussian_blur", "motion_blur", "gaussian_noise", "jpeg_compression", "resolution_loss")
SEED = 20261004


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def magick(*args: str) -> str:
    return subprocess.check_output(["magick", *args], text=True).strip()


def size(path: Path) -> tuple[int, int]:
    return tuple(map(int, magick("identify", "-format", "%w %h", str(path)).split()))


def relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def baseline() -> tuple[list[dict[str, str]], dict[str, Any]]:
    clean_metadata = CATALOG / "ocr_metadata.clean.json"
    clean_report = CATALOG / "ocr_selection_report.clean.json"
    if not clean_metadata.exists():
        metadata = json.loads((CATALOG / "ocr_metadata.json").read_text())
        report = json.loads((CATALOG / "ocr_selection_report.json").read_text())
        if any(not item["image"].startswith("datasets/external/") for item in metadata):
            raise ValueError("Cannot establish a clean baseline from transformed images")
        write_json_atomic(metadata, clean_metadata)
        write_json_atomic(report, clean_report)
    return json.loads(clean_metadata.read_text()), json.loads(clean_report.read_text())


def plan(metadata: list[dict[str, str]], report: dict[str, Any]) -> dict[str, Any]:
    indices = random.Random(SEED).sample(range(len(metadata)), round(len(metadata) * 0.15))
    assignments = [(method, level) for method in METHODS for level in (1, 2, 3)]
    assignments = (assignments * math.ceil(len(indices) / len(assignments)))[:len(indices)]
    random.Random(SEED + 1).shuffle(assignments)
    references = {ref["image"]: ref for ref in report["selected_references"]}
    records = []
    for index, (method, level) in zip(indices, assignments, strict=True):
        item, reference = metadata[index], references[metadata[index]["image"]]
        width, height = size(ROOT / item["image"])
        heights = sorted(region["bbox_xywh"][3] for region in reference["regions"] or []
                         if "bbox_xywh" in region and region["bbox_xywh"][3] > 0)
        critical_height = heights[int((len(heights) - 1) * 0.1)] if heights else None
        scale = min(1.5, max(0.25, (critical_height or 18) / 18))
        if method == "gaussian_blur":
            parameters = {"sigma_px": round((0.45, 0.85, 1.25)[level - 1] * scale, 3)}
        elif method == "motion_blur":
            parameters = {"sigma_px": round((0.55, 1.0, 1.5)[level - 1] * scale, 3),
                          "angle_degrees": random.Random(f"{SEED}:{index}").choice([0, 45, 90])}
        elif method == "gaussian_noise":
            parameters = {"attenuate": (0.025, 0.055, 0.09)[level - 1], "seed": SEED + index}
        elif method == "jpeg_compression":
            parameters = {"quality": (80, 55, 35)[level - 1], "sampling_factor": "4:2:0"}
        else:
            factor = (0.85, 0.65, 0.45)[level - 1]
            if critical_height:
                factor = max(factor, min(0.98, 9 / critical_height))
            parameters = {"scale": round(factor, 4), "filter": "Lanczos",
                          "restore_original_dimensions": True}
        source_hash = digest(ROOT / item["image"])
        if source_hash != reference["sha256"]:
            raise ValueError(f"Source changed: {item['image']}")
        output = OUTPUT / "images" / f"{index:04d}_{method}_s{level}.png"
        records.append({"catalog_index": index, "source_image": item["image"],
                        "output_image": relative(output), "source_sha256": source_hash,
                        "category": item["category"], "method": method, "severity": level,
                        "width": width, "height": height, "critical_text_height_px": critical_height,
                        "parameters": parameters, "strength_multiplier": 1.0,
                        "review": {"status": "pending"}})
    return {"seed": SEED, "fraction": 0.15, "input_count": len(metadata),
            "transformed_count": len(records),
            "clean_metadata_sha256": digest(CATALOG / "ocr_metadata.clean.json"),
            "image_engine": magick("-version").splitlines()[0],
            "methods": dict(Counter(record["method"] for record in records)),
            "categories": dict(Counter(record["category"] for record in records)),
            "policy": "Whole-image filters only; exact text and source category unchanged. Source images are immutable. Severity capped by critical text height and visual review. No claim of a universal readability threshold.",
            "records": records}


def render_record(record: dict[str, Any]) -> dict[str, Any]:
    source, output = ROOT / record["source_image"], ROOT / record["output_image"]
    output.parent.mkdir(parents=True, exist_ok=True)
    if digest(source) != record["source_sha256"]:
        raise ValueError(f"Source image changed: {source}")
    strength = record["strength_multiplier"]
    if not 0 < strength <= 1:
        raise ValueError("Strength multipliers must be in (0, 1]")
    parameters, method = record["parameters"], record["method"]
    command = ["-limit", "thread", "1", str(source), "-background", "white", "-alpha", "remove", "-alpha", "off"]
    actual = dict(parameters)
    if method in {"gaussian_blur", "motion_blur"}:
        # Smaller kernels can round to an identity operation at 8-bit precision.
        minimum_sigma = 0.3 if method == "gaussian_blur" else 0.4
        actual["sigma_px"] = max(minimum_sigma, round(parameters["sigma_px"] * strength, 5))
        actual["minimum_effective_sigma_px"] = minimum_sigma
        geometry = f"0x{actual['sigma_px']}"
        if method == "motion_blur":
            geometry += f"+{parameters['angle_degrees']}"
        command += ["-blur" if method == "gaussian_blur" else "-motion-blur", geometry]
    elif method == "gaussian_noise":
        actual["attenuate"] = round(parameters["attenuate"] * strength, 5)
        command += ["-seed", str(parameters["seed"]), "-attenuate", str(actual["attenuate"]), "+noise", "Gaussian"]
    elif method == "jpeg_compression":
        actual["quality"] = round(100 - (100 - parameters["quality"]) * strength)
        temporary = output.with_suffix(".intermediate.jpg")
        magick(*command, "-sampling-factor", parameters["sampling_factor"], "-quality", str(actual["quality"]), "-strip", str(temporary))
        command = [str(temporary)]
    elif method == "resolution_loss":
        actual["scale"] = round(1 - (1 - parameters["scale"]) * strength, 5)
        reduced_width = max(1, round(record["width"] * actual["scale"]))
        reduced_height = max(1, round(record["height"] * actual["scale"]))
        actual["intermediate_dimensions"] = [reduced_width, reduced_height]
        command += ["-filter", parameters["filter"], "-resize", f"{reduced_width}x{reduced_height}!",
                    "-resize", f"{record['width']}x{record['height']}!"]
    else:
        raise ValueError(f"Unknown method: {method}")
    magick(*command, "-depth", "8", "-strip", "-define", "png:exclude-chunks=date,time", "PNG24:" + str(output))
    if method == "jpeg_compression":
        temporary.unlink()
    if size(output) != (record["width"], record["height"]):
        raise ValueError(f"Output dimensions changed: {output}")
    record["actual_parameters"] = actual
    record["output_sha256"] = digest(output)
    record["review"] = {"status": "pending"}
    return record


def review_crop(reference: dict[str, Any], width: int, height: int) -> tuple[int, int, int, int]:
    regions = reference["regions"] or []
    if regions and "bbox_xywh" not in regions[0]:
        # MM-SafetyBench declares a target panel, not individual words.
        region = regions[0]
        box = region.get("bbox") or region.get("bbox_xywh")
        if box:
            x, y, w, h = box
            return max(0, int(x)), max(0, int(y)), min(width, math.ceil(w)), min(height, math.ceil(h))
    return 0, 0, width, height


def previews(manifest: dict[str, Any], report: dict[str, Any], only: list[int] | None = None) -> None:
    """Create before/after sheets including small-text windows at enlarged scale."""
    review_dir = OUTPUT / "review"
    review_dir.mkdir(parents=True, exist_ok=True)
    references = {reference["image"]: reference for reference in report["selected_references"]}
    tiles = []
    for number, record in enumerate(manifest["records"]):
        tile = review_dir / f"tile_{number:03d}.png"
        tiles.append(tile)
        if only is not None and number not in only and tile.exists():
            continue
        reference = references[record["source_image"]]
        words = [region for region in reference["regions"] or [] if "bbox_xywh" in region]
        words.sort(key=lambda region: (region["bbox_xywh"][3], -len(region["text"])))
        windows = []
        if words:
            # Small text is particularly vulnerable. Inspect additional longer text too.
            candidates = words[:2] + [max(words, key=lambda region: len(region["text"]))]
            for region in candidates:
                x, y, w, h = region["bbox_xywh"]
                left, top = max(0, math.floor(x) - 4), max(0, math.floor(y) - 4)
                windows.append((left, top, min(record["width"] - left, math.ceil(w) + 8),
                                min(record["height"] - top, math.ceil(h) + 8)))
        else:
            windows = [review_crop(reference, record["width"], record["height"])]
        panels = []
        for label, key in (("ORIGINAL", "source_image"), ("VARIANTE", "output_image")):
            source = ROOT / record[key]
            full = review_dir / f"{number:03d}_{label}_full.png"
            magick(str(source), "-thumbnail", "440x270", "-background", "white", "-gravity", "center", "-extent", "450x280", "-strip", str(full))
            patches = []
            for window_index, (x, y, w, h) in enumerate(windows):
                patch = review_dir / f"{number:03d}_{label}_patch_{window_index}.png"
                magick(str(source), "-crop", f"{w}x{h}+{x}+{y}", "+repage", "-filter", "point",
                       "-resize", "200%", "-resize", "440x96>", "-background", "white", "-gravity", "center", "-extent", "450x100", "-strip", str(patch))
                patches.append(str(patch))
            panel = review_dir / f"{number:03d}_{label}.png"
            magick(str(full), *patches, "-append", str(panel))
            panels.append(str(panel))
        caption = f"#{number:03d} index={record['catalog_index']} {record['category']} {record['method']} s{record['severity']} x{record['strength_multiplier']} | ORIGINAL links / VARIANTE rechts"
        magick(*panels, "+append", "-background", "white", "-fill", "black", "-font", "/System/Library/Fonts/Supplemental/Arial.ttf", "-pointsize", "14",
               "-gravity", "northwest", "-splice", "0x25", "-annotate", "+5+5", caption, str(tile))
    for start in range(0, len(tiles), 6):
        sheet = review_dir / f"sheet_{start // 6:02d}.jpg"
        magick(*(str(tile) for tile in tiles[start:start + 6]), "-background", "#d0d0d0", "-append", "-strip", "-quality", "95", str(sheet))
    # Web-page targets are too small in the overview; inspect at native resolution.
    vpi_tiles = []
    for number, record in enumerate(manifest["records"]):
        if record["category"] != "vpi_bench":
            continue
        name = Path(record["source_image"]).name
        window = "640x230+350+100" if name.startswith("messenger_") else (
            "740x660+270+150" if name.startswith("email_") else "570x560+225+140")
        panels = []
        for key in ("source_image", "output_image"):
            panel = review_dir / f"vpi_{number}_{key}.png"
            magick(str(ROOT / record[key]), "-crop", window, "+repage", "-strip", str(panel))
            panels.append(str(panel))
        tile = review_dir / f"vpi_{number:03d}.jpg"
        caption = f"#{number:03d} {record['method']} x{record['strength_multiplier']} ORIGINAL links / VARIANTE rechts"
        magick(*panels, "+append", "-background", "white", "-fill", "black", "-font",
               "/System/Library/Fonts/Supplemental/Arial.ttf", "-pointsize", "18", "-gravity",
               "northwest", "-splice", "0x30", "-annotate", "+5+5", caption, "-quality", "98", str(tile))
        vpi_tiles.append(tile)
    for start in range(0, len(vpi_tiles), 3):
        magick(*(str(tile) for tile in vpi_tiles[start:start + 3]), "-append",
               str(review_dir / f"vpi_sheet_{start // 3}.jpg"))
    adjusted = [tile for tile, record in zip(tiles, manifest["records"], strict=True)
                if record["strength_multiplier"] < 1]
    for start in range(0, len(adjusted), 5):
        magick(*(str(tile) for tile in adjusted[start:start + 5]), "-append",
               str(review_dir / f"adjusted_sheet_{start // 5}.jpg"))


def apply(manifest: dict[str, Any], metadata: list[dict[str, str]], report: dict[str, Any]) -> None:
    if digest(CATALOG / "ocr_metadata.clean.json") != manifest["clean_metadata_sha256"]:
        raise ValueError("Clean catalog changed")
    expected = random.Random(manifest["seed"]).sample(range(len(metadata)), round(len(metadata) * manifest["fraction"]))
    if (len(metadata) != manifest["input_count"] or
            len(manifest["records"]) != manifest["transformed_count"] or
            [record["catalog_index"] for record in manifest["records"]] != expected):
        raise ValueError("Random selection does not match the recorded seed/fraction")
    updated = [dict(item) for item in metadata]
    references = {reference["image"]: reference for reference in report["selected_references"]}
    for record in manifest["records"]:
        if record["review"].get("status") != "accepted":
            raise ValueError(f"Visual review still pending: {record['output_image']}")
        if record["review"].get("reviewed_output_sha256") != record["output_sha256"]:
            raise ValueError("Visual review does not match the rendered image")
        if digest(ROOT / record["source_image"]) != record["source_sha256"] or digest(ROOT / record["output_image"]) != record["output_sha256"]:
            raise ValueError("Image changed since rendering/review")
        index = record["catalog_index"]
        if updated[index]["image"] != record["source_image"]:
            raise ValueError("Image mapping changed")
        updated[index]["image"] = record["output_image"]
        reference = references[record["source_image"]]
        reference["original_image"] = reference["image"]
        reference["original_sha256"] = reference["sha256"]
        reference["image"] = record["output_image"]
        reference["sha256"] = record["output_sha256"]
        reference["derivation"] = {"method": record["method"], "parameters": record["actual_parameters"],
                                   "review": record["review"]}
    report["augmentation"] = {"manifest": relative(MANIFEST), "count": len(manifest["records"]),
                              "seed": manifest["seed"], "clean_metadata": relative(CATALOG / "ocr_metadata.clean.json")}
    schema = json.loads((CATALOG / "ocr_metadata.schema.json").read_text())
    Draft202012Validator(schema).validate(updated)
    current = json.loads((CATALOG / "ocr_metadata.json").read_text())
    extensions = [item for item in current if item["category"] == "anamorpher"]
    current_base = [item for item in current if item["category"] != "anamorpher"]
    if current_base != metadata and current_base != updated:
        raise ValueError("Active catalog changed independently; refusing to overwrite it")
    if extensions:
        current_report = json.loads((CATALOG / "ocr_selection_report.json").read_text())
        extension_paths = {item["image"] for item in extensions}
        report["selected_references"].extend(ref for ref in current_report["selected_references"]
                                             if ref["image"] in extension_paths)
        for key in ("selected_counts", "eligible_counts"):
            report[key]["anamorpher"] = len(extensions)
        report["selected_count"] = len(updated) + len(extensions)
        report["scope_counts"] = dict(Counter(ref["scope"] for ref in report["selected_references"]))
        report["quality_counts"] = dict(Counter(ref["annotation"]["quality"] for ref in report["selected_references"]))
        report["excluded_sources"] = [name for name in report["excluded_sources"] if name != "anamorpher"]
        report["anamorpher"] = current_report["anamorpher"]
        report["limitations"] = current_report["limitations"]
        updated.extend(extensions)
        Draft202012Validator(schema).validate(updated)
    write_json_atomic(updated, CATALOG / "ocr_metadata.json")
    write_json_atomic(report, CATALOG / "ocr_selection_report.json")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("render", "apply", "previews"))
    parser.add_argument("--only", nargs="*", type=int, help="Only rerender these manifest positions")
    args = parser.parse_args()
    metadata, report = baseline()
    manifest = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else plan(metadata, report)
    if args.mode == "render":
        selected = [(index, record) for index, record in enumerate(manifest["records"])
                    if args.only is None or index in args.only]
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            futures = {pool.submit(render_record, record): index for index, record in selected}
            for future in concurrent.futures.as_completed(futures):
                manifest["records"][futures[future]] = future.result()
        write_json_atomic(manifest, MANIFEST)
        previews(manifest, report, args.only)
    elif args.mode == "previews":
        previews(manifest, report, args.only)
    else:
        apply(manifest, metadata, report)
    print(json.dumps({"mode": args.mode, "transformed_count": manifest["transformed_count"],
                      "methods": manifest["methods"], "categories": manifest["categories"]}, indent=2))


if __name__ == "__main__":
    main()
