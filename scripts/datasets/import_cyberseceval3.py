#!/usr/bin/env python3
"""Import CyberSecEval3 Visual Prompt Injection into the shared catalog."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import struct
import tempfile
import unicodedata
from pathlib import Path
from typing import Any, Iterable, Sequence


SCHEMA_VERSION = "1.0.0"
DATASET_ID = "cyberseceval3_visual_prompt_injection"
UPSTREAM_REPOSITORY = "facebook/cyberseceval3-visual-prompt-injection"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    project_root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(
        description="Create catalog metadata for CyberSecEval3 visual prompt injection."
    )
    parser.add_argument(
        "--source-root",
        type=Path,
        default=project_root
        / "datasets/external/facebook/cyberseceval3-visual-prompt-injection",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=project_root
        / "datasets/catalog/sources/cyberseceval3_visual_prompt_injection.jsonl",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Validate source records and images without writing metadata.",
    )
    return parser.parse_args(argv)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def png_properties(path: Path) -> tuple[int, int, str, int]:
    with path.open("rb") as handle:
        header = handle.read(26)
    if len(header) != 26 or header[:8] != PNG_SIGNATURE or header[12:16] != b"IHDR":
        raise ValueError(f"Not a valid PNG with an IHDR header: {path}")
    width, height = struct.unpack(">II", header[16:24])
    bit_depth = header[24]
    color_modes = {0: "L", 2: "RGB", 3: "P", 4: "LA", 6: "RGBA"}
    try:
        color_mode = color_modes[header[25]]
    except KeyError as exc:
        raise ValueError(f"Unsupported PNG color type {header[25]} in {path}") from exc
    return width, height, color_mode, bit_depth


def normalize_transcript(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text).split())


def stable_group_id(text: str, fallback: str) -> str:
    material = normalize_transcript(text) or normalize_transcript(fallback)
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:20]
    return f"{DATASET_ID}:content:{digest}"


def detect_revision(source_root: Path) -> str | None:
    tree_dir = source_root / ".cache/huggingface/trees"
    revisions = sorted(path.stem for path in tree_dir.glob("*.json"))
    return revisions[0] if len(revisions) == 1 else None


def extract_transcript(item: dict[str, Any]) -> tuple[str, str, str]:
    transcript = str(item.get("image_text") or "")
    if transcript:
        return transcript, "source_declared_text", "upstream.image_text"

    techniques = set(item.get("injection_technique", []))
    if "virtualization" in techniques:
        match = re.fullmatch(
            r"Does this response contain '([^']+)'\?", str(item["judge_question"])
        )
        if not match:
            raise ValueError(
                f"Cannot derive virtualization target for upstream id {item['id']}"
            )
        return match.group(1), "target_text_only", "derived.judge_question"

    raise ValueError(f"No OCR transcript source for upstream id {item['id']}")


def scene_type(item: dict[str, Any]) -> str:
    techniques = set(item.get("injection_technique", []))
    if "virtualization" in techniques:
        return "captcha_on_scene"
    if "figstep" in techniques:
        return "text_only"
    return "overlay_on_scene"


def text_layout(item: dict[str, Any]) -> str:
    techniques = set(item.get("injection_technique", []))
    if "virtualization" in techniques:
        return "captcha"
    if "figstep" in techniques:
        return "numbered_list"
    return "overlay"


def build_record(
    item: dict[str, Any], source_root: Path, project_root: Path, revision: str | None
) -> dict[str, Any]:
    upstream_id = item["id"]
    image_path = source_root / "images" / f"{upstream_id}.png"
    if not image_path.is_file():
        raise FileNotFoundError(f"Missing image for record {upstream_id}: {image_path}")

    transcript, transcript_scope, transcript_provenance = extract_transcript(item)
    description = str(item.get("image_description") or "")
    normalized = normalize_transcript(transcript)
    width, height, color_mode, bit_depth = png_properties(image_path)
    relative_path = image_path.resolve().relative_to(project_root.resolve()).as_posix()
    techniques = sorted(set(item.get("injection_technique", [])))
    has_ground_truth_text = bool(normalized)

    return {
        "schema_version": SCHEMA_VERSION,
        "sample_id": f"{DATASET_ID}:{int(upstream_id):06d}",
        "asset": {
            "path": relative_path,
            "sha256": sha256_file(image_path),
            "media_type": "image/png",
            "format": "png",
            "width": width,
            "height": height,
            "color_mode": color_mode,
            "bit_depth": bit_depth,
            "bytes": image_path.stat().st_size,
        },
        "source": {
            "dataset_id": DATASET_ID,
            "upstream_id": str(upstream_id),
            "repository": UPSTREAM_REPOSITORY,
            "revision": revision,
            "split": "test",
            "license_spdx": "MIT",
        },
        "group": {
            "content_group_id": stable_group_id(
                transcript, description or f"upstream-record:{upstream_id}"
            ),
            "content_basis": "ocr_transcript",
            "variant": "source_image",
            "parent_sample_id": None,
        },
        "visual": {
            "scene_type": scene_type(item),
            "text_layout": text_layout(item),
            "challenge_tags": techniques,
            "generation_type": "synthetic",
        },
        "ocr": {
            "has_ground_truth_text": has_ground_truth_text,
            "transcript_verbatim": transcript,
            "transcript_normalized": normalized,
            "scope": transcript_scope,
            "languages": [] if transcript_scope == "target_text_only" else ["en"],
            "scripts": ["Latn"],
            "reading_order_known": True,
            "regions": None,
            "annotation": {
                "provenance": transcript_provenance,
                "quality": "silver",
                "verified": False,
            },
        },
        "security": {
            "attack_family": "visual_prompt_injection",
            "injection_techniques": techniques,
            "injection_type": item.get("injection_type"),
            "risk_category": item.get("risk_category"),
            "contains_injection_instruction": True,
            "contains_harmful_instruction": None,
        },
        "eligibility": {
            "ocr_eval": True,
            "evaluation_mode": "transcription",
            "training": False,
            "exclusion_reasons": [],
        },
        "rights": {
            "commercial_use": True,
            "training_use": False,
            "attribution_required": True,
            "usage_notes": "Dataset card designates the benchmark for evaluation, not training.",
        },
        "source_specific": {
            "system_prompt": item.get("system_prompt"),
            "user_input_text": item.get("user_input_text"),
            "image_description": item.get("image_description"),
            "judge_question": item.get("judge_question"),
        },
    }


def load_records(source_root: Path) -> list[dict[str, Any]]:
    metadata_path = source_root / "test_cases.json"
    with metadata_path.open(encoding="utf-8") as handle:
        records = json.load(handle)
    if not isinstance(records, list):
        raise ValueError(f"Expected a JSON array in {metadata_path}")
    return records


def load_omitted_sample_ids(project_root: Path) -> set[str]:
    """Keep user-excluded OCR cases out of regenerated active source shards."""
    omitted: set[str] = set()
    archive_dir = project_root / "datasets/catalog/excluded_sources"
    for archive in sorted(archive_dir.glob("cyberseceval3_*_omitted_from_ocr.jsonl")):
        with archive.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"Invalid JSON in {archive}:{line_number}: {exc}") from exc
                sample_id = record.get("sample_id")
                if not isinstance(sample_id, str) or not sample_id.startswith(f"{DATASET_ID}:"):
                    raise ValueError(f"Invalid archived sample_id in {archive}:{line_number}")
                omitted.add(sample_id)
    return omitted


def validate_records(records: Iterable[dict[str, Any]]) -> None:
    seen_ids: set[Any] = set()
    for position, item in enumerate(records):
        missing = {
            "id",
            "injection_technique",
            "injection_type",
            "risk_category",
            "system_prompt",
            "user_input_text",
            "judge_question",
        } - item.keys()
        if missing:
            raise ValueError(f"Record {position} is missing fields: {sorted(missing)}")
        if item["id"] in seen_ids:
            raise ValueError(f"Duplicate upstream id: {item['id']}")
        seen_ids.add(item["id"])


def write_jsonl_atomic(records: Iterable[dict[str, Any]], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{output.name}.", suffix=".tmp", dir=output.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            for record in records:
                json.dump(record, handle, ensure_ascii=False, separators=(",", ":"))
                handle.write("\n")
        Path(temporary_name).replace(output)
    except Exception:
        Path(temporary_name).unlink(missing_ok=True)
        raise


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    source_root = args.source_root.resolve()
    project_root = Path(__file__).resolve().parents[2]
    upstream_records = load_records(source_root)
    validate_records(upstream_records)
    revision = detect_revision(source_root)
    omitted_sample_ids = load_omitted_sample_ids(project_root)
    records = [
        build_record(item, source_root, project_root, revision)
        for item in sorted(upstream_records, key=lambda record: int(record["id"]))
        if f"{DATASET_ID}:{int(item['id']):06d}" not in omitted_sample_ids
    ]

    sample_ids = [record["sample_id"] for record in records]
    if len(sample_ids) != len(set(sample_ids)):
        raise ValueError("Generated sample ids are not unique")

    if not args.validate_only:
        write_jsonl_atomic(records, args.output.resolve())

    mode = "Validated" if args.validate_only else "Wrote"
    provenance_counts: dict[str, int] = {}
    for record in records:
        provenance = record["ocr"]["annotation"]["provenance"]
        provenance_counts[provenance] = provenance_counts.get(provenance, 0) + 1
    print(f"{mode} {len(records)} records for {DATASET_ID}: {provenance_counts}.")
    if not args.validate_only:
        print(f"Output: {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
