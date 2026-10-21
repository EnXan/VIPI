#!/usr/bin/env python3
"""Build an archival PHANTOM shard without treating prompts as OCR transcripts."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import struct
import tempfile
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO, Sequence


SCHEMA_VERSION = "1.0.0"
DATASET_ID = "phantom"
REPOSITORY = "https://huggingface.co/datasets/it4lia/PHANTOM"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
STRATEGY_VISUALS = {
    "BAP": ("natural_image", "unknown", ["adversarial_perturbation"]),
    "IDEATOR": ("mixed_scene", "unknown", ["generated_scene", "multi_turn_possible"]),
    "MML": ("text_only", "transformed_text", ["rotated_or_mirrored_text"]),
    "FC_ATTACK": ("diagram", "flowchart", ["flowchart_text"]),
    "CSDJ": ("collage", "multi_panel", ["mixed_image_and_text_panels"]),
}


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=root / "research/datasets/data/external/it4lia/PHANTOM")
    parser.add_argument(
        "--output",
        type=Path,
        default=root / "research/datasets/data/catalog/excluded_sources/phantom.jsonl",
    )
    parser.add_argument(
        "--audit-output", type=Path, default=root / "research/datasets/data/catalog/reports/phantom_import_audit.json"
    )
    return parser.parse_args(argv)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def png_properties(handle: BinaryIO) -> tuple[int, int, str, int]:
    header = handle.read(26)
    if len(header) != 26 or header[:8] != PNG_SIGNATURE or header[12:16] != b"IHDR":
        raise ValueError("Invalid PNG header")
    width, height = struct.unpack(">II", header[16:24])
    bit_depth = header[24]
    color_mode = {0: "L", 2: "RGB", 3: "P", 4: "LA", 6: "RGBA"}.get(header[25])
    if color_mode is None or width < 1 or height < 1:
        raise ValueError("Unsupported PNG properties")
    return width, height, color_mode, bit_depth


def jpeg_properties(handle: BinaryIO) -> tuple[int, int, str, int]:
    if handle.read(2) != b"\xff\xd8":
        raise ValueError("Invalid JPEG header")
    sof_markers = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
    while True:
        prefix = handle.read(1)
        if not prefix:
            raise ValueError("JPEG has no frame header")
        if prefix != b"\xff":
            continue
        marker = handle.read(1)
        while marker == b"\xff":
            marker = handle.read(1)
        if not marker:
            raise ValueError("Truncated JPEG marker")
        code = marker[0]
        if code in {0x01, 0xD8} or 0xD0 <= code <= 0xD7:
            continue
        if code in {0xD9, 0xDA}:
            raise ValueError("JPEG has no frame header")
        length_bytes = handle.read(2)
        if len(length_bytes) != 2:
            raise ValueError("Truncated JPEG segment")
        length = struct.unpack(">H", length_bytes)[0]
        if length < 2:
            raise ValueError("Invalid JPEG segment length")
        if code in sof_markers:
            frame = handle.read(6)
            if len(frame) != 6:
                raise ValueError("Truncated JPEG frame header")
            bit_depth, height, width, channels = struct.unpack(">BHHB", frame)
            color_mode = {1: "L", 3: "RGB", 4: "CMYK"}.get(channels)
            if color_mode is None or width < 1 or height < 1:
                raise ValueError("Unsupported JPEG properties")
            return width, height, color_mode, bit_depth
        handle.seek(length - 2, os.SEEK_CUR)


def image_properties(path: Path) -> tuple[int, int, str, int]:
    with path.open("rb") as handle:
        try:
            if path.suffix.lower() == ".png":
                return png_properties(handle)
            if path.suffix.lower() in {".jpg", ".jpeg"}:
                return jpeg_properties(handle)
        except ValueError as exc:
            raise ValueError(f"{path}: {exc}") from exc
    raise ValueError(f"Unsupported image format: {path}")


def detect_revision(source_root: Path) -> str | None:
    revisions = sorted(path.stem for path in (source_root / ".cache/huggingface/trees").glob("*.json"))
    return revisions[0] if len(revisions) == 1 else None


def release_manifest_paths(source_root: Path, revision: str | None) -> set[str] | None:
    if revision is None:
        return None
    manifest = source_root / ".cache/huggingface/trees" / f"{revision}.json"
    with manifest.open(encoding="utf-8") as handle:
        return set(json.load(handle)["files"])


def image_path_for(source_root: Path, file_name: str) -> Path:
    pure = PurePosixPath(file_name)
    if pure.is_absolute() or ".." in pure.parts or not pure.parts:
        raise ValueError(f"Unsafe PHANTOM image path: {file_name}")
    return source_root.joinpath(*pure.parts)


def build_record(
    row: dict[str, Any], image_path: Path, project_root: Path, revision: str | None
) -> dict[str, Any]:
    strategy = row["strategy"]
    scene_type, text_layout, tags = STRATEGY_VISUALS[strategy]
    step = int(row["step"])
    attack_id = str(row["id"])
    sample_id = f"phantom:{attack_id}:step:{step}"
    width, height, color_mode, bit_depth = image_properties(image_path)
    extension = image_path.suffix.lower()
    relative_path = image_path.relative_to(project_root).as_posix()
    return {
        "schema_version": SCHEMA_VERSION,
        "sample_id": sample_id,
        "asset": {
            "path": relative_path,
            "sha256": sha256_file(image_path),
            "media_type": "image/png" if extension == ".png" else "image/jpeg",
            "format": "png" if extension == ".png" else "jpeg",
            "width": width,
            "height": height,
            "color_mode": color_mode,
            "bit_depth": bit_depth,
            "bytes": image_path.stat().st_size,
        },
        "source": {
            "dataset_id": DATASET_ID,
            "upstream_id": f"{attack_id}:step:{step}",
            "repository": REPOSITORY,
            "revision": revision,
            "split": "train",
            "license_spdx": "CC-BY-4.0",
        },
        "group": {
            "content_group_id": f"phantom:attack:{attack_id}",
            "content_basis": "upstream_attack_id",
            "variant": f"{strategy.lower()}_step_{step}",
            "parent_sample_id": (f"phantom:{attack_id}:step:1" if step > 1 else None),
        },
        "visual": {
            "scene_type": scene_type,
            "text_layout": text_layout,
            "challenge_tags": [strategy.lower(), *tags],
            "generation_type": "adversarial_perturbation" if strategy == "BAP" else "generated",
        },
        "ocr": {
            "has_ground_truth_text": False,
            "transcript_verbatim": "",
            "transcript_normalized": "",
            "scope": "none",
            "languages": [],
            "scripts": [],
            "reading_order_known": False,
            "regions": None,
            "annotation": {
                "provenance": "upstream.no_image_transcript",
                "quality": "unlabeled",
                "verified": False,
            },
        },
        "security": {
            "attack_family": "visual_jailbreak",
            "injection_techniques": [strategy.lower()],
            "injection_type": "multimodal_adversarial_prompt",
            "risk_category": row["main_category"],
            "contains_injection_instruction": strategy in {"MML", "FC_ATTACK", "CSDJ"},
            "contains_harmful_instruction": None,
        },
        "eligibility": {
            "ocr_eval": False,
            "evaluation_mode": "image_transcript_missing",
            "training": False,
            "exclusion_reasons": ["no_verified_image_transcript"],
        },
        "rights": {
            "commercial_use": True,
            "training_use": True,
            "attribution_required": True,
            "usage_notes": "PHANTOM dataset card specifies CC BY 4.0; retain attribution.",
        },
        "source_specific": {
            "attack_id": attack_id,
            "goal": row["goal"],
            "target_model": row["target_model"],
            "main_category": row["main_category"],
            "subcategory": row["subcategory"],
            "strategy": strategy,
            "number_of_steps": int(row["number_of_steps"]),
            "step": step,
            "prompt": row["prompt"],
            "sd_model": row["sd_model"],
            "upstream_file_name": row["file_name"],
            "visual_category_basis": "strategy_heuristic",
            "image_text_note": "goal and prompt are not exact visible-image transcripts",
        },
    }


def write_json_atomic(value: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        Path(temporary_name).replace(path)
    except Exception:
        Path(temporary_name).unlink(missing_ok=True)
        raise


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    project_root = Path(__file__).resolve().parents[2].resolve()
    source_root = args.source_root.resolve()
    revision = detect_revision(source_root)
    manifest_paths = release_manifest_paths(source_root, revision)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{args.output.name}.", suffix=".tmp", dir=args.output.parent
    )
    source_counts: Counter[str] = Counter()
    imported_counts: Counter[str] = Counter()
    missing_images: list[dict[str, Any]] = []
    seen_sample_ids: set[str] = set()
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            with (source_root / "metadata.jsonl").open(encoding="utf-8") as source:
                for line_number, line in enumerate(source, start=1):
                    if not line.strip():
                        continue
                    row = json.loads(line)
                    strategy = row["strategy"]
                    if strategy not in STRATEGY_VISUALS:
                        raise ValueError(f"Unknown strategy on line {line_number}: {strategy}")
                    source_counts[strategy] += 1
                    image_path = image_path_for(source_root, row["file_name"])
                    if not image_path.is_file():
                        missing_images.append({
                            "source_line": line_number,
                            "attack_id": row["id"],
                            "step": row["step"],
                            "file_name": row["file_name"],
                        })
                        continue
                    record = build_record(row, image_path, project_root, revision)
                    if record["sample_id"] in seen_sample_ids:
                        raise ValueError(f"Duplicate sample_id: {record['sample_id']}")
                    seen_sample_ids.add(record["sample_id"])
                    json.dump(record, output, ensure_ascii=False, separators=(",", ":"))
                    output.write("\n")
                    imported_counts[strategy] += 1
                    if sum(imported_counts.values()) % 5000 == 0:
                        print(f"Imported {sum(imported_counts.values())} PHANTOM images...", flush=True)
        audit = {
            "source_metadata_rows": sum(source_counts.values()),
            "imported_image_rows": sum(imported_counts.values()),
            "missing_image_rows": len(missing_images),
            "missing_images_listed_in_release_manifest": (
                sum(item["file_name"] in manifest_paths for item in missing_images)
                if manifest_paths is not None else None
            ),
            "source_rows_by_strategy": dict(sorted(source_counts.items())),
            "imported_rows_by_strategy": dict(sorted(imported_counts.items())),
            "missing_images": missing_images,
            "ocr_eval_ready": 0,
            "note": "PHANTOM does not supply exact visible-image transcripts; goal and prompt are not OCR ground truth.",
        }
        write_json_atomic(audit, args.audit_output)
        Path(temporary_name).replace(args.output)
    except Exception:
        Path(temporary_name).unlink(missing_ok=True)
        raise
    print(
        f"Wrote {sum(imported_counts.values())} PHANTOM records; "
        f"{len(missing_images)} source rows reference missing images."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
