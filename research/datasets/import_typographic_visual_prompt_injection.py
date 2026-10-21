#!/usr/bin/env python3
"""Import Dagger7164 typographic prompt images and their source-declared text."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import struct
import tempfile
import unicodedata
from pathlib import Path
from typing import Any, Iterable, Sequence


SCHEMA_VERSION = "1.0.0"
DATASET_ID = "typographic_visual_prompt_injection"
REPOSITORY = "https://huggingface.co/datasets/Dagger7164/VisualPromptInjection"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
STYLES = ("clean", "lowcontrast", "distorted")
CATEGORIES = {
    "V-01": "System Bypass",
    "V-02": "Data Privacy",
    "V-03": "Content Policy",
}
TEXT_COLORS = {
    "clean": [0, 0, 0],
    "lowcontrast": [200, 200, 200],
    "distorted": [0, 0, 0],
}


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    project_root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-root",
        type=Path,
        default=project_root / "research/datasets/data/external/Dagger7164/VisualPromptInjection",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=project_root
        / "research/datasets/data/catalog/sources/typographic_visual_prompt_injection.jsonl",
    )
    parser.add_argument(
        "--validate-only", action="store_true", help="Validate source rows and images only."
    )
    return parser.parse_args(argv)


def load_rows(source_root: Path) -> list[dict[str, str]]:
    path = source_root / "prompts.csv"
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        expected_fields = (
            "vector_id", "category", "prompt_id", "prompt_text", "expected_response"
        )
        if tuple(reader.fieldnames or ()) != expected_fields:
            raise ValueError(f"Unexpected columns in {path}: {reader.fieldnames}")
        rows = list(reader)
    if len(rows) != 45:
        raise ValueError(f"Expected 45 prompt rows, found {len(rows)}")
    seen_ids: set[str] = set()
    counts: dict[str, int] = {key: 0 for key in CATEGORIES}
    for line_number, row in enumerate(rows, start=2):
        if any(not row[field] for field in expected_fields):
            raise ValueError(f"Empty field in {path}:{line_number}")
        vector_id = row["vector_id"]
        if vector_id not in CATEGORIES or row["category"] != CATEGORIES[vector_id]:
            raise ValueError(f"Unexpected vector/category in {path}:{line_number}")
        if not row["prompt_id"].startswith(vector_id.replace("-", "") + "-P"):
            raise ValueError(f"Prompt ID does not match vector in {path}:{line_number}")
        if row["prompt_id"] in seen_ids:
            raise ValueError(f"Duplicate prompt ID: {row['prompt_id']}")
        if row["expected_response"] != "REFUSE":
            raise ValueError(f"Unexpected expected response in {path}:{line_number}")
        seen_ids.add(row["prompt_id"])
        counts[vector_id] += 1
    if set(counts.values()) != {15}:
        raise ValueError(f"Expected 15 prompts per vector, found {counts}")
    return rows


def validate_images(source_root: Path, rows: list[dict[str, str]]) -> None:
    image_root = source_root / "images"
    expected = {f"{row['prompt_id']}_{style}.png" for row in rows for style in STYLES}
    actual = {path.name for path in image_root.glob("*.png")}
    if expected != actual:
        raise ValueError(
            f"Image mismatch: missing={sorted(expected - actual)}, extra={sorted(actual - expected)}"
        )


def png_properties(path: Path) -> tuple[int, int, str, int]:
    with path.open("rb") as handle:
        header = handle.read(26)
    if len(header) != 26 or header[:8] != PNG_SIGNATURE or header[12:16] != b"IHDR":
        raise ValueError(f"Invalid PNG header: {path}")
    width, height = struct.unpack(">II", header[16:24])
    bit_depth = header[24]
    color_mode = {0: "L", 2: "RGB", 3: "P", 4: "LA", 6: "RGBA"}.get(header[25])
    if color_mode is None or width < 1 or height < 1:
        raise ValueError(f"Unsupported PNG properties: {path}")
    return width, height, color_mode, bit_depth


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def detect_revision(source_root: Path) -> str | None:
    revisions = sorted(path.stem for path in (source_root / ".cache/huggingface/trees").glob("*.json"))
    return revisions[0] if len(revisions) == 1 else None


def build_record(
    row: dict[str, str], style: str, source_root: Path, project_root: Path, revision: str | None
) -> dict[str, Any]:
    prompt_id = row["prompt_id"]
    path = source_root / "images" / f"{prompt_id}_{style}.png"
    width, height, color_mode, bit_depth = png_properties(path)
    if (width, height, color_mode, bit_depth) != (512, 256, "RGB", 8):
        raise ValueError(f"Unexpected image properties in {path}")
    transcript = row["prompt_text"]
    normalized = " ".join(unicodedata.normalize("NFC", transcript).split())
    sample_id = f"{DATASET_ID}:{prompt_id}:{style}"
    tags = ["typographic_visual_prompt", "wrapped_text"]
    if style == "lowcontrast":
        tags.append("low_contrast")
    elif style == "distorted":
        tags.append("oblique_font")
    return {
        "schema_version": SCHEMA_VERSION,
        "sample_id": sample_id,
        "asset": {
            "path": path.relative_to(project_root).as_posix(),
            "sha256": sha256_file(path),
            "media_type": "image/png",
            "format": "png",
            "width": width,
            "height": height,
            "color_mode": color_mode,
            "bit_depth": bit_depth,
            "bytes": path.stat().st_size,
        },
        "source": {
            "dataset_id": DATASET_ID,
            "upstream_id": f"{prompt_id}_{style}",
            "repository": REPOSITORY,
            "revision": revision,
            "split": None,
            "license_spdx": "MIT",
        },
        "group": {
            "content_group_id": f"{DATASET_ID}:prompt:{prompt_id}",
            "content_basis": "upstream_prompt_id",
            "variant": style,
            "parent_sample_id": (
                None if style == "clean" else f"{DATASET_ID}:{prompt_id}:clean"
            ),
        },
        "visual": {
            "scene_type": "text_only",
            "text_layout": "wrapped_paragraph",
            "challenge_tags": tags,
            "generation_type": "rendered",
        },
        "ocr": {
            "has_ground_truth_text": True,
            "transcript_verbatim": transcript,
            "transcript_normalized": normalized,
            "scope": "source_declared_text",
            "languages": ["en"],
            "scripts": ["Latn"],
            "reading_order_known": True,
            "regions": None,
            "annotation": {
                "provenance": "upstream.prompts_csv.prompt_text",
                "quality": "silver",
                "verified": False,
            },
        },
        "security": {
            "attack_family": "visual_prompt_injection",
            "injection_techniques": ["typographic_visual_prompt"],
            "injection_type": "direct_visual",
            "risk_category": row["category"],
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
            "training_use": True,
            "attribution_required": True,
            "usage_notes": (
                "MIT license; dataset card says it is not intended to train models "
                "to perform the attacks. OCR training is outside this catalog phase."
            ),
        },
        "source_specific": {
            "vector_id": row["vector_id"],
            "category": row["category"],
            "prompt_id": prompt_id,
            "expected_response": row["expected_response"],
            "style": style,
            "declared_text_color_rgb": TEXT_COLORS[style],
            "declared_background_rgb": [255, 255, 255],
            "declared_font_style": "oblique" if style == "distorted" else "sans_serif",
            "declared_font_size_pt": 20,
            "declared_padding_px": 20,
            "layout_line_breaks_in_source": False,
        },
    }


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
    project_root = Path(__file__).resolve().parents[2].resolve()
    source_root = args.source_root.resolve()
    rows = load_rows(source_root)
    validate_images(source_root, rows)
    revision = detect_revision(source_root)
    records = [
        build_record(row, style, source_root, project_root, revision)
        for row in rows
        for style in STYLES
    ]
    if len({record["sample_id"] for record in records}) != 135:
        raise ValueError("Expected 135 unique sample IDs")
    if not args.validate_only:
        write_jsonl_atomic(records, args.output)
    print(f"Validated {len(rows)} prompts and {len(records)} typographic images.")
    if not args.validate_only:
        print(f"Output: {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
