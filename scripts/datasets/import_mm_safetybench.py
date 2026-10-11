#!/usr/bin/env python3
"""Import MM-SafetyBench's rendered text variants for target-text OCR evaluation."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import struct
import tempfile
import unicodedata
from pathlib import Path
from typing import Any, Sequence


DATASET_ID = "mm_safetybench"
REPOSITORY = "https://github.com/isXinLiu/MM-SafetyBench"
VARIANTS = ("TYPO", "SD_TYPO")
SOF_MARKERS = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    project_root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=project_root / "datasets/external/MM-SafetyBench")
    parser.add_argument(
        "--output",
        type=Path,
        default=project_root / "datasets/catalog/sources/mm_safetybench.jsonl",
    )
    parser.add_argument(
        "--audit",
        type=Path,
        default=project_root / "datasets/catalog/reports/mm_safetybench_import_audit.json",
    )
    parser.add_argument("--validate-only", action="store_true")
    return parser.parse_args(argv)


def jpeg_properties(path: Path) -> tuple[int, int, str, int]:
    """Read dimensions and color components from the JPEG start-of-frame marker."""
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
            if code in SOF_MARKERS:
                frame = handle.read(6)
                if len(frame) != 6:
                    break
                bit_depth, height, width, components = struct.unpack(">BHHB", frame)
                color_mode = {1: "L", 3: "RGB", 4: "CMYK"}.get(components)
                if not color_mode or not width or not height:
                    break
                return width, height, color_mode, bit_depth
            handle.seek(segment_length - 2, os.SEEK_CUR)
    raise ValueError(f"No supported JPEG start-of-frame marker: {path}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text).split())


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


def build_record(
    scenario: str,
    question_id: str,
    question: dict[str, str],
    variant: str,
    image_root: Path,
    source_root: Path,
    project_root: Path,
    revision: str | None,
) -> dict[str, Any]:
    path = image_root / scenario / variant / f"{question_id}.jpg"
    width, height, color_mode, bit_depth = jpeg_properties(path)
    phrase = question["Key Phrase"]
    if variant == "TYPO":
        region = [0, 0, width, height]
        scene_type = "text_only"
        text_layout = "wrapped_phrase"
        tags = ["typographic_visual_phrase"]
        scope = "source_declared_text"
        parent_sample_id = None
    else:
        background_path = image_root / scenario / "SD" / f"{question_id}.jpg"
        text_path = image_root / scenario / "TYPO" / f"{question_id}.jpg"
        background_width, background_height, _, _ = jpeg_properties(background_path)
        text_width, text_height, _, _ = jpeg_properties(text_path)
        if (width, height) != (
            max(background_width, text_width),
            background_height + text_height,
        ):
            raise ValueError(f"Unexpected SD_TYPO geometry: {path}")
        region = [0, background_height, text_width, text_height]
        scene_type = "rendered_text_below_scene"
        text_layout = "bottom_text_panel"
        tags = ["typographic_visual_phrase", "scene_plus_text"]
        scope = "target_text_only"
        parent_sample_id = f"{DATASET_ID}:{scenario}:{question_id}:TYPO"
    relative_path = path.relative_to(project_root).as_posix()
    return {
        "schema_version": "1.0.0",
        "sample_id": f"{DATASET_ID}:{scenario}:{question_id}:{variant}",
        "asset": {
            "path": relative_path,
            "sha256": sha256_file(path),
            "media_type": "image/jpeg",
            "format": "jpeg",
            "width": width,
            "height": height,
            "color_mode": color_mode,
            "bit_depth": bit_depth,
            "bytes": path.stat().st_size,
        },
        "source": {
            "dataset_id": DATASET_ID,
            "upstream_id": f"{scenario}/{question_id}/{variant}",
            "repository": REPOSITORY,
            "revision": revision,
            "split": None,
            "license_spdx": "CC-BY-NC-4.0",
        },
        "group": {
            "content_group_id": f"{DATASET_ID}:{scenario}:{question_id}",
            "content_basis": "scenario_and_question_id",
            "variant": variant,
            "parent_sample_id": parent_sample_id,
        },
        "visual": {
            "scene_type": scene_type,
            "text_layout": text_layout,
            "challenge_tags": tags,
            "generation_type": "rendered_typography",
        },
        "ocr": {
            "has_ground_truth_text": True,
            "transcript_verbatim": phrase,
            "transcript_normalized": normalize(phrase),
            "scope": scope,
            "languages": ["en"],
            "scripts": ["Latn"],
            "reading_order_known": True,
            "regions": [{
                "bbox_xywh": region,
                "coordinate_system": "absolute_pixels",
                "role": "injected_text",
                "text": phrase,
            }],
            "annotation": {
                "provenance": "upstream.processed_questions.Key Phrase",
                "quality": "silver",
                "verified": False,
            },
        },
        "security": {
            "attack_family": "query_relevant_visual_jailbreak",
            "injection_techniques": ["typographic_visual_phrase"],
            "injection_type": "direct_visual",
            "risk_category": scenario,
            "contains_injection_instruction": False,
            "contains_harmful_instruction": None,
        },
        "eligibility": {
            "ocr_eval": True,
            "evaluation_mode": "transcription",
            "training": False,
            "exclusion_reasons": [],
        },
        "rights": {
            "commercial_use": False,
            "training_use": None,
            "attribution_required": True,
            "usage_notes": (
                "CC BY-NC 4.0; noncommercial research use only. Upstream also requires "
                "compliance with GPT-4 and Stable Diffusion terms. Training is out of scope."
            ),
        },
        "source_specific": {
            "scenario": scenario,
            "question_id": question_id,
            "phrase_type": question["Phrase Type"],
            "key_phrase": phrase,
            "variant": variant,
            "source_question_path": (
                source_root / "data/processed_questions" / f"{scenario}.json"
            ).relative_to(project_root).as_posix(),
            "line_breaks_in_source": False,
            "background_may_contain_unlabeled_text": variant == "SD_TYPO",
        },
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    project_root = Path(__file__).resolve().parents[2].resolve()
    source_root = args.source_root.resolve()
    image_root = source_root / "MM-SafetyBench(imgs)"
    question_files = sorted((source_root / "data/processed_questions").glob("*.json"))
    if len(question_files) != 13:
        raise ValueError(f"Expected 13 scenario JSON files, found {len(question_files)}")
    revision_file = source_root / ".git/HEAD"
    revision = None
    if revision_file.exists():
        import subprocess
        revision = subprocess.check_output(
            ["git", "-C", str(source_root), "rev-parse", "HEAD"], text=True
        ).strip()
    records: list[dict[str, Any]] = []
    orphans: list[str] = []
    for question_file in question_files:
        scenario = question_file.stem
        questions = json.loads(question_file.read_text(encoding="utf-8"))
        if not isinstance(questions, dict):
            raise ValueError(f"Expected question ID mapping in {question_file}")
        expected_ids = set(questions)
        for question_id, question in sorted(questions.items(), key=lambda pair: int(pair[0])):
            if not question_id.isdecimal():
                raise ValueError(f"Non-numeric question ID: {scenario}/{question_id}")
            if not all(question.get(key) for key in ("Key Phrase", "Phrase Type")):
                raise ValueError(f"Missing phrase metadata: {scenario}/{question_id}")
            for variant in VARIANTS:
                path = image_root / scenario / variant / f"{question_id}.jpg"
                if not path.is_file():
                    raise FileNotFoundError(f"Missing image: {path}")
                records.append(build_record(
                    scenario, question_id, question, variant, image_root,
                    source_root, project_root, revision,
                ))
            if not (image_root / scenario / "SD" / f"{question_id}.jpg").is_file():
                raise FileNotFoundError(f"Missing SD background: {scenario}/{question_id}")
        for variant in ("SD", *VARIANTS):
            actual = {p.stem for p in (image_root / scenario / variant).glob("*.jpg")}
            missing = expected_ids - actual
            if missing:
                raise ValueError(f"Missing {variant} images in {scenario}: {sorted(missing)}")
            orphans.extend(
                (image_root / scenario / variant / f"{question_id}.jpg")
                .relative_to(project_root).as_posix()
                for question_id in sorted(actual - expected_ids, key=int)
            )
    if len(records) != 3360 or len({r["sample_id"] for r in records}) != len(records):
        raise ValueError(f"Expected 3,360 unique OCR records, found {len(records)}")
    audit = {
        "dataset_id": DATASET_ID,
        "question_count": len(records) // 2,
        "ocr_record_count": len(records),
        "variants": list(VARIANTS),
        "excluded_sd_background_count": len(records) // 2,
        "orphan_image_count": len(orphans),
        "orphan_images": orphans,
        "ocr_scope_note": (
            "TYPO uses the source-declared phrase. SD_TYPO evaluates only its bottom "
            "text panel; incidental text in the SD background is not transcribed."
        ),
    }
    if not args.validate_only:
        write_json_atomic(records, args.output, jsonl=True)
        write_json_atomic(audit, args.audit)
    print(
        f"Validated {len(records) // 2} matched questions, {len(records)} OCR records, "
        f"{len(orphans)} excluded orphan images."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
