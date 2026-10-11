#!/usr/bin/env python3
"""Build a reproducible, balanced OCR sample with image, text and source category."""

from __future__ import annotations

import argparse
import csv
import json
import random
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

import import_cyberseceval3 as cyber
import import_mm_safetybench as mm
import import_typographic_visual_prompt_injection as typography
import import_vpi_bench as vpi
import import_textocr as textocr


ROOT = Path(__file__).resolve().parents[2]
OCR_DIR = ROOT / "datasets/catalog/ocr"
DATASETS = (cyber.DATASET_ID, mm.DATASET_ID, typography.DATASET_ID, vpi.DATASET_ID, textocr.DATASET_ID)


def source_records() -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Reconstruct source-backed references without modifying upstream files."""
    records = []
    excluded = []
    source = ROOT / "datasets/external/facebook/cyberseceval3-visual-prompt-injection"
    items = cyber.load_records(source)
    cyber.validate_records(items)
    revision = cyber.detect_revision(source)
    # Judge targets are not image transcripts. Only explicit image_text qualifies.
    for item in items:
        sample_id = f"{cyber.DATASET_ID}:{int(item['id']):06d}"
        if not (source / "images" / f"{item['id']}.png").is_file():
            excluded.append({"sample_id": sample_id, "reason": "missing_image"})
        elif not item.get("image_text", "").strip():
            excluded.append({"sample_id": sample_id, "reason": "judge_target_is_not_image_transcript"})
        else:
            records.append(cyber.build_record(item, source, ROOT, revision))

    source = ROOT / "datasets/external/Dagger7164/VisualPromptInjection"
    rows = typography.load_rows(source)
    typography.validate_images(source, rows)
    revision = typography.detect_revision(source)
    records.extend(typography.build_record(row, style, source, ROOT, revision)
                   for row in rows for style in typography.STYLES)

    source = ROOT / "datasets/external/MM-SafetyBench"
    image_root = source / "MM-SafetyBench(imgs)"
    question_files = sorted((source / "data/processed_questions").glob("*.json"))
    if len(question_files) != 13:
        raise ValueError("Expected 13 MM-SafetyBench scenario files")
    for path in question_files:
        questions = json.loads(path.read_text(encoding="utf-8"))
        for question_id, question in sorted(questions.items(), key=lambda pair: int(pair[0])):
            if not question.get("Key Phrase", "").strip():
                raise ValueError(f"Missing Key Phrase: {path}:{question_id}")
            records.extend(mm.build_record(path.stem, question_id, question, variant,
                                           image_root, source, ROOT, None)
                           for variant in mm.VARIANTS)

    plan = json.loads((ROOT / "datasets/external/VPI-Bench/capture_plan.json").read_text())
    records.extend(vpi.build_record(item, ROOT) for item in plan)
    textocr_records, textocr_exclusions = textocr.build_records(ROOT)
    records.extend(textocr_records)
    excluded.extend(textocr_exclusions)
    return records, excluded


def eligible_records(records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    eligible = []
    excluded = []
    seen_hashes: dict[str, dict[str, Any]] = {}
    seen_ids: set[str] = set()
    for record in sorted(records, key=lambda item: item["sample_id"]):
        sample_id = record["sample_id"]
        if sample_id in seen_ids:
            raise ValueError(f"Duplicate sample ID: {sample_id}")
        seen_ids.add(sample_id)
        ocr = record["ocr"]
        if (not record["eligibility"]["ocr_eval"] or not ocr["has_ground_truth_text"]
                or not ocr["transcript_verbatim"].strip()
                or ocr["scope"] in {"none", "source_declared_no_text"}):
            excluded.append({"sample_id": sample_id, "reason": "no_usable_ocr_reference"})
            continue
        path = ROOT / record["asset"]["path"]
        path.resolve().relative_to(ROOT)
        if not path.is_file():
            raise FileNotFoundError(path)
        checksum = cyber.sha256_file(path)
        if checksum != record["asset"]["sha256"]:
            raise ValueError(f"Source image changed: {path}")
        if checksum in seen_hashes:
            previous = seen_hashes[checksum]
            if cyber.normalize_transcript(ocr["transcript_verbatim"]) != cyber.normalize_transcript(
                    previous["ocr"]["transcript_verbatim"]):
                raise ValueError(f"Conflicting texts for identical images: {sample_id}")
            excluded.append({"sample_id": sample_id, "reason": "duplicate_image",
                             "duplicate_of": previous["sample_id"]})
            continue
        seen_hashes[checksum] = record
        eligible.append(record)
    return eligible, excluded


def balanced_counts(capacities: dict[str, int], count: int) -> dict[str, int]:
    """Distribute evenly, redistributing quotas exhausted by small datasets."""
    if count <= 0 or count > sum(capacities.values()):
        raise ValueError(f"Requested {count} images, available {sum(capacities.values())}")
    quotas = dict.fromkeys(sorted(capacities), 0)
    for _ in range(count):
        available = [key for key in quotas if quotas[key] < capacities[key]]
        key = min(available, key=lambda key: (quotas[key], key))
        quotas[key] += 1
    return quotas


def selection_counts(capacities: dict[str, int], count: int, textocr_share: float) -> dict[str, int]:
    if not 0 < textocr_share < 1:
        raise ValueError("TextOCR share must be between 0 and 1, exclusive")
    textocr_count = int(count * textocr_share + 0.5)
    if not 0 < textocr_count < count or textocr_count > capacities[textocr.DATASET_ID]:
        raise ValueError("Requested TextOCR quota cannot be satisfied")
    quotas = balanced_counts({key: capacity for key, capacity in capacities.items()
                              if key != textocr.DATASET_ID}, count - textocr_count)
    quotas[textocr.DATASET_ID] = textocr_count
    return quotas


def build(count: int, seed: int, textocr_share: float = 0.5) -> tuple[list[dict[str, str]], dict[str, Any]]:
    reconstructed, source_exclusions = source_records()
    records, excluded = eligible_records(reconstructed)
    excluded = source_exclusions + excluded
    pools = defaultdict(list)
    for record in records:
        pools[record["source"]["dataset_id"]].append(record)
    if set(pools) != set(DATASETS):
        raise ValueError(f"Expected five OCR datasets, found {sorted(pools)}")
    quotas = selection_counts({key: len(pool) for key, pool in pools.items()}, count, textocr_share)
    selected = []
    for dataset_id in sorted(pools):
        rng = random.Random(f"{seed}:{dataset_id}")
        pool = sorted(pools[dataset_id], key=lambda record: record["sample_id"])
        selected.extend(rng.sample(pool, quotas[dataset_id]))
    random.Random(seed).shuffle(selected)
    metadata = [{"image": record["asset"]["path"],
                 "text": record["ocr"]["transcript_verbatim"],
                 "category": record["source"]["dataset_id"]} for record in selected]
    schema = json.loads((OCR_DIR / "ocr_metadata.schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(metadata)
    if len({item["image"] for item in metadata}) != count:
        raise ValueError("Duplicate image paths in selection")
    report = {
        "seed": seed, "requested_count": count, "selected_count": len(selected),
        "image_paths_relative_to": "repository_root",
        "sampling": "uniform_random_without_replacement_per_dataset; fixed_textocr_share; capacity_limited_equal_quotas_for_other_sources",
        "textocr_share": textocr_share,
        "eligible_counts": {key: len(pools[key]) for key in sorted(pools)},
        "selected_counts": quotas,
        "scope_counts": dict(Counter(record["ocr"]["scope"] for record in selected)),
        "quality_counts": dict(Counter(record["ocr"]["annotation"]["quality"] for record in selected)),
        "excluded_records": excluded,
        "excluded_sources": ["figstep", "anamorpher", "phantom", "prism",
                             "visinject", "multimodal_injection", "visual_adversarial_examples"],
        "limitations": [
            "CyberSecEval3 cases without image_text (100 CAPTCHA judge targets) are excluded.",
            "MM-SafetyBench SD backgrounds and orphan images without a matching Key Phrase are excluded.",
            "VPI-Bench uses source-declared target texts from the 190 non-BBC captures; prior Gold labels are not reconstructed.",
            "Target-only/source-declared references do not certify all visible text. See selected_references for scope and regions.",
            "No evaluation splits are created. Keep content_group_id together in future splits.",
            "References are reconstructed as Silver from raw sources, without recovering prior manual corrections from Trash.",
            "TextOCR is sampled randomly without difficulty labels; scene complexity is not a verified attack-frequency measure.",
            "TextOCR '.' annotations (unreadable or non-English text) are ignored, not transcribed as periods. See ignored_regions.",
            "TextOCR word texts are joined by newlines in source annotation order; no full-image reading order is guaranteed. Evaluate matched word regions to avoid reading-order errors.",
        ],
        "selected_references": [{
            "image": record["asset"]["path"], "sample_id": record["sample_id"],
            "sha256": record["asset"]["sha256"],
            "content_group_id": record["group"]["content_group_id"],
            "scope": record["ocr"]["scope"], "regions": record["ocr"]["regions"],
            "reading_order_known": record["ocr"]["reading_order_known"],
            "ignored_regions": record["ocr"].get("ignored_regions", []),
            "annotation": record["ocr"]["annotation"],
            "repository": record["source"]["repository"],
            "rights": record.get("rights"),
        } for record in selected],
    }
    return metadata, report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--textocr-share", type=float, default=0.5)
    args = parser.parse_args()
    metadata, report = build(args.count, args.seed, args.textocr_share)
    mm.write_json_atomic(metadata, OCR_DIR / "ocr_metadata.json")
    mm.write_json_atomic(report, OCR_DIR / "ocr_selection_report.json")
    # Retire only the empty placeholder; never delete a nonempty legacy catalog.
    placeholder = OCR_DIR / "ocr_metadata.jsonl"
    if placeholder.is_file() and placeholder.stat().st_size == 0:
        placeholder.unlink()
    with (OCR_DIR / "ocr_datasets.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["dataset_id", "available_ocr_images", "selected_ocr_images"])
        writer.writerows((key, report["eligible_counts"][key], value)
                         for key, value in report["selected_counts"].items())
    print(json.dumps({"selected": report["selected_count"],
                      "eligible": report["eligible_counts"],
                      "counts": report["selected_counts"],
                      "scopes": report["scope_counts"]}, indent=2))


if __name__ == "__main__":
    main()
