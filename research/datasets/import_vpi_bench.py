#!/usr/bin/env python3
"""Import captured VPI-Bench pages as source-declared OCR target records."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import struct
import tempfile
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any, Sequence


DATASET_ID = "vpi_bench"
REPOSITORY = "https://huggingface.co/datasets/VPI-Bench/vpi-bench"
PLATFORM_METADATA = {
    "amazon": ("webpage_popup", "modal_overlay_description", "popup_text"),
    "booking": ("webpage_popup", "modal_overlay_description", "popup_text"),
    "email": ("email_inbox", "selected_email_body", "email_message"),
    "messenger": ("messenger_chat", "selected_chat_message", "chat_message"),
}


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    project_root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--capture-plan", type=Path,
        default=project_root / "research/datasets/data/external/VPI-Bench/capture_plan.json",
    )
    parser.add_argument(
        "--output", type=Path,
        default=project_root / "research/datasets/data/catalog/sources/vpi_bench.jsonl",
    )
    parser.add_argument(
        "--audit", type=Path,
        default=project_root / "research/datasets/data/catalog/reports/vpi_bench_capture_audit.json",
    )
    parser.add_argument("--validate-only", action="store_true")
    return parser.parse_args(argv)


def normalize(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text).split())


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def jpeg_properties(path: Path) -> tuple[int, int, str, int]:
    """Return dimensions, color mode and depth from JPEG frame metadata."""
    sof_markers = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
    with path.open("rb") as handle:
        if handle.read(2) != b"\xff\xd8":
            raise ValueError(f"Invalid JPEG signature: {path}")
        while True:
            marker_start = handle.read(1)
            if not marker_start:
                break
            if marker_start != b"\xff":
                raise ValueError(f"Invalid JPEG marker in {path}")
            marker = handle.read(1)
            while marker == b"\xff":
                marker = handle.read(1)
            if not marker:
                break
            code = marker[0]
            if code in {0x01, 0xD8} or 0xD0 <= code <= 0xD7:
                continue
            if code in {0xD9, 0xDA}:
                break
            raw_length = handle.read(2)
            if len(raw_length) != 2:
                break
            segment_length = struct.unpack(">H", raw_length)[0]
            if segment_length < 2:
                break
            if code in sof_markers:
                frame = handle.read(6)
                if len(frame) != 6:
                    break
                bit_depth, height, width, components = struct.unpack(">BHHB", frame)
                color_mode = {1: "L", 3: "RGB", 4: "CMYK"}.get(components)
                if not color_mode or not width or not height:
                    break
                return width, height, color_mode, bit_depth
            handle.seek(segment_length - 2, os.SEEK_CUR)
    raise ValueError(f"No supported JPEG frame marker: {path}")


def build_record(item: dict[str, Any], project_root: Path) -> dict[str, Any]:
    image_path = project_root / item["screenshot"]
    if not image_path.is_file():
        raise FileNotFoundError(f"Screenshot missing for {item['url']}: {image_path}")
    transcript = item["source_target_text"].strip()
    if not transcript:
        raise ValueError(f"Empty visible target text for {item['url']}")
    platform = item["platform"]
    if platform not in PLATFORM_METADATA:
        raise ValueError(f"Unknown VPI-Bench platform: {platform}")
    scene_type, text_layout, technique = PLATFORM_METADATA[platform]
    width, height, color_mode, bit_depth = jpeg_properties(image_path)
    normalized = normalize(transcript)
    group_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
    source_config = json.loads((project_root / item["config"]).read_text(encoding="utf-8"))
    local_background = item.get("background_image_exists_locally")
    tags = ["visual_prompt_injection", platform]
    if platform in {"amazon", "booking", "bbc"}:
        tags.append("modal_popup")
    if local_background is False:
        tags.append("source_background_missing")
    return {
        "schema_version": "1.0.0",
        "sample_id": f"{DATASET_ID}:{Path(item['screenshot']).stem}",
        "asset": {
            "path": item["screenshot"],
            "sha256": sha256_file(image_path),
            "media_type": "image/jpeg",
            "format": "jpeg",
            "width": width,
            "height": height,
            "color_mode": color_mode,
            "bit_depth": bit_depth,
            "bytes": image_path.stat().st_size,
        },
        "source": {
            "dataset_id": DATASET_ID,
            "upstream_id": item["url"],
            "repository": REPOSITORY,
            "revision": None,
            "split": "test",
            "license_spdx": "CC-BY-4.0",
        },
        "group": {
            "content_group_id": f"{DATASET_ID}:target:{group_hash}",
            "content_basis": "sha256_of_normalized_source_declared_target_text",
            "variant": platform,
            "parent_sample_id": None,
        },
        "visual": {
            "scene_type": scene_type,
            "text_layout": text_layout,
            "challenge_tags": tags,
            "generation_type": "live_webpage_screenshot",
        },
        "ocr": {
            "has_ground_truth_text": True,
            "transcript_verbatim": transcript,
            "transcript_normalized": normalized,
            "scope": "target_text_only",
            "languages": ["en"],
            "scripts": ["Latn"],
            "reading_order_known": True,
            "regions": None,
            "annotation": {
                "provenance": item["config"],
                "quality": "silver",
                "verified": False,
            },
        },
        "security": {
            "attack_family": "visual_prompt_injection",
            "injection_techniques": [technique],
            "injection_type": platform,
            "risk_category": None,
            "contains_injection_instruction": True,
            "contains_harmful_instruction": None,
        },
        "eligibility": {
            "ocr_eval": True,
            "evaluation_mode": "source_declared_target_transcription",
            "training": False,
            "exclusion_reasons": [],
        },
        "rights": {
            "commercial_use": True,
            "training_use": False,
            "attribution_required": True,
            "usage_notes": (
                "CC BY 4.0. Attribute VPI-Bench and its authors. The dataset card states "
                "that the benchmark is not intended for model training."
            ),
        },
        "source_specific": {
            "platform": platform,
            "testcase_ids": item["testcase_ids"],
            "testcase_paths": item["testcases"],
            "source_config_path": item["config"],
            "screenshot_url": item["url"],
            "target_text_field": (
                "description" if platform in {"amazon", "booking", "bbc"}
                else "selected_email.content" if platform == "email"
                else "selected_chat.history.message"
            ),
            "configured_background_image": source_config.get("backgroundImage"),
            "background_image_exists_locally": local_background,
            "captured_viewport_px": [width, height],
            "other_visible_text_untranscribed": True,
            "text_regions_manually_annotated": False,
        },
    }


def write_json_atomic(value: Any, path: Path, *, jsonl: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            if jsonl:
                for record in value:
                    json.dump(record, handle, ensure_ascii=False, separators=(",", ":"))
                    handle.write("\n")
            else:
                json.dump(value, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
        Path(temporary_name).replace(path)
    except Exception:
        Path(temporary_name).unlink(missing_ok=True)
        raise


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    project_root = Path(__file__).resolve().parents[2].resolve()
    plan_path = args.capture_plan.resolve()
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    records = [build_record(item, project_root) for item in plan]
    sample_ids = [record["sample_id"] for record in records]
    if len(sample_ids) != len(set(sample_ids)):
        raise ValueError("Duplicate sample IDs in VPI-Bench capture plan")

    screenshot_dir = project_root / "research/datasets/data/external/VPI-Bench/screenshots"
    referenced = {record["asset"]["path"] for record in records}
    unreferenced = sorted(
        path.relative_to(project_root).as_posix()
        for path in screenshot_dir.glob("*.jpg")
        if path.relative_to(project_root).as_posix() not in referenced
    )
    background_missing = [
        record["sample_id"]
        for record in records
        if record["source_specific"]["background_image_exists_locally"] is False
    ]
    audit = {
        "planned_unique_urls": len(plan),
        "testcase_references": sum(len(item["testcase_ids"]) for item in plan),
        "records": len(records),
        "ocr_eval_records": sum(record["eligibility"]["ocr_eval"] for record in records),
        "screenshots_by_platform": dict(Counter(item["platform"] for item in plan)),
        "missing_screenshots": [],
        "source_background_missing_count": len(background_missing),
        "source_background_missing_samples": background_missing,
        "unreferenced_screenshots": unreferenced,
        "screenshot_dimensions": sorted(
            {f"{record['asset']['width']}x{record['asset']['height']}" for record in records}
        ),
        "transcripts_are_source_declared_silver": True,
        "text_regions_annotated": False,
    }
    if args.validate_only:
        print(json.dumps(audit, ensure_ascii=False, indent=2))
        return 0

    output = args.output.resolve()
    audit_path = args.audit.resolve()
    write_json_atomic(records, output, jsonl=True)
    write_json_atomic(audit, audit_path)
    print(f"Wrote {len(records)} records to {output}")
    print(f"Wrote capture audit to {audit_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
