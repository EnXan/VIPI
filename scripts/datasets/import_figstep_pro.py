#!/usr/bin/env python3
"""Import FigStep-Pro fragments and preserve their manual annotations."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import struct
import tempfile
import unicodedata
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Sequence


SCHEMA_VERSION = "1.0.0"
DATASET_ID = "figstep"
UPSTREAM_REPOSITORY = "https://github.com/CryptoAILab/FigStep"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
PLACEHOLDER = "__FILL_ME__"
VERIFIED = "verified"

GROUP_FIELDS = (
    "group_index",
    "group_name",
    "parent_sample_id",
    "category_id",
    "task_id",
    "category_name",
    "question",
    "instruction",
    "benign_template",
    "group_transcript",
    "mapping_status",
    "notes",
)
FRAGMENT_FIELDS = (
    "group_index",
    "fragment_index",
    "fragment_count",
    "archive_member",
    "asset_path",
    "fragment_transcript",
    "notes",
)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    project_root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-root", type=Path, default=project_root / "datasets/external/FigStep"
    )
    parser.add_argument(
        "--extract-root", "--derived-root",
        dest="extract_root",
        type=Path,
        default=None,
    )
    parser.add_argument(
        "--manual-root",
        type=Path,
        default=project_root / "datasets/catalog/manual",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=project_root / "datasets/catalog/sources/figstep_pro.jsonl",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Validate existing templates and assets without writing the source shard.",
    )
    return parser.parse_args(argv)


def normalize_transcript(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text).split())


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


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def write_csv_atomic(path: Path, fieldnames: Sequence[str], rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        Path(temporary_name).replace(path)
    except Exception:
        Path(temporary_name).unlink(missing_ok=True)
        raise


def archive_members(archive_path: Path) -> dict[int, list[tuple[int, str]]]:
    pattern = re.compile(
        r"^image_(?P<group>\d+)_splits/image_\d+_split_(?P<fragment>\d+)\.png$"
    )
    groups: dict[int, list[tuple[int, str]]] = {}
    with zipfile.ZipFile(archive_path) as archive:
        for name in archive.namelist():
            match = pattern.fullmatch(name)
            if not match:
                continue
            group_index = int(match.group("group"))
            fragment_index = int(match.group("fragment"))
            groups.setdefault(group_index, []).append((fragment_index, name))
    for members in groups.values():
        members.sort()
    return dict(sorted(groups.items()))


def extract_fragments(
    archive_path: Path, extract_root: Path, groups: dict[int, list[tuple[int, str]]]
) -> None:
    expected_members = {name for members in groups.values() for _, name in members}
    with zipfile.ZipFile(archive_path) as archive:
        for member in sorted(expected_members):
            pure_path = PurePosixPath(member)
            if pure_path.is_absolute() or ".." in pure_path.parts:
                raise ValueError(f"Unsafe archive member: {member}")
            output = extract_root.joinpath(*pure_path.parts)
            output.parent.mkdir(parents=True, exist_ok=True)
            data = archive.read(member)
            if output.exists() and output.read_bytes() == data:
                continue
            output.write_bytes(data)


def create_templates_if_missing(
    source_root: Path,
    extract_root: Path,
    manual_root: Path,
    groups: dict[int, list[tuple[int, str]]],
    project_root: Path,
) -> tuple[Path, Path]:
    groups_path = manual_root / "figstep_pro_groups.csv"
    fragments_path = manual_root / "figstep_pro_fragments.csv"
    tiny_rows = load_csv(source_root / "data/question/SafeBench-Tiny.csv")
    benign_rows = load_csv(
        source_root / "data/question/benign_sentences_without_harmful_phase.csv"
    )
    if len(groups) != 50 or len(tiny_rows) != 50 or len(benign_rows) != 50:
        raise ValueError(
            "FigStep-Pro positional mapping requires 50 archive groups, 50 Tiny rows, "
            "and 50 benign templates"
        )

    if not groups_path.exists():
        group_rows = []
        for group_index, tiny_row in enumerate(tiny_rows):
            group_rows.append(
                {
                    "group_index": group_index,
                    "group_name": f"image_{group_index}_splits",
                    "parent_sample_id": (
                        f"figstep:{tiny_row['dataset'].lower()}:"
                        f"{int(tiny_row['category_id']):02d}:"
                        f"{int(tiny_row['task_id']):03d}:safebench_tiny"
                    ),
                    "category_id": int(tiny_row["category_id"]),
                    "task_id": int(tiny_row["task_id"]),
                    "category_name": tiny_row["category_name"],
                    "question": tiny_row["question"],
                    "instruction": tiny_row["instruction"],
                    "benign_template": benign_rows[group_index]["sentence"],
                    "group_transcript": PLACEHOLDER,
                    "mapping_status": "unverified_positional",
                    "notes": "",
                }
            )
        write_csv_atomic(groups_path, GROUP_FIELDS, group_rows)

    if not fragments_path.exists():
        fragment_rows = []
        for group_index, members in groups.items():
            for fragment_index, archive_member in members:
                asset_path = extract_root.joinpath(*PurePosixPath(archive_member).parts)
                fragment_rows.append(
                    {
                        "group_index": group_index,
                        "fragment_index": fragment_index,
                        "fragment_count": len(members),
                        "archive_member": archive_member,
                        "asset_path": asset_path.resolve()
                        .relative_to(project_root.resolve())
                        .as_posix(),
                        "fragment_transcript": PLACEHOLDER,
                        "notes": "",
                    }
                )
        write_csv_atomic(fragments_path, FRAGMENT_FIELDS, fragment_rows)
    return groups_path, fragments_path


def templates_from_source_shard(
    shard_path: Path,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Recover editable annotation rows from an already annotated FigStep-Pro shard."""
    grouped_rows: dict[int, dict[str, str]] = {}
    fragment_rows: list[dict[str, str]] = []
    seen_ids: set[str] = set()

    with shard_path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                source_specific = record["source_specific"]
                group_index = int(source_specific["group_index"])
                fragment_index = int(source_specific["fragment_index"])
                sample_id = record["sample_id"]
            except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                raise ValueError(
                    f"Invalid embedded annotation in {shard_path}:{line_number}"
                ) from exc

            expected_id = (
                f"figstep_pro:group:{group_index:03d}:fragment:{fragment_index:03d}"
            )
            if sample_id != expected_id or sample_id in seen_ids:
                raise ValueError(
                    f"Unexpected or duplicate FigStep-Pro sample ID in "
                    f"{shard_path}:{line_number}: {sample_id}"
                )
            seen_ids.add(sample_id)

            group_row = {
                "group_index": str(group_index),
                "group_name": f"image_{group_index}_splits",
                "parent_sample_id": str(record["group"]["parent_sample_id"]),
                "category_id": str(source_specific["category_id"]),
                "task_id": str(source_specific["task_id"]),
                "category_name": str(source_specific["category_name"]),
                "question": str(source_specific["question"]),
                "instruction": str(source_specific["instruction"]),
                "benign_template": str(source_specific["benign_template"]),
                "group_transcript": str(source_specific["group_transcript"]),
                "mapping_status": str(source_specific["mapping_status"]),
                "notes": str(source_specific["manual_notes"]["group"]),
            }
            previous_group = grouped_rows.setdefault(group_index, group_row)
            if previous_group != group_row:
                raise ValueError(
                    f"Inconsistent embedded group annotation for group {group_index}"
                )

            fragment_rows.append(
                {
                    "group_index": str(group_index),
                    "fragment_index": str(fragment_index),
                    "fragment_count": str(source_specific["fragment_count"]),
                    "archive_member": str(source_specific["archive_member"]),
                    "asset_path": str(record["asset"]["path"]),
                    "fragment_transcript": str(record["ocr"]["transcript_verbatim"]),
                    "notes": str(source_specific["manual_notes"]["fragment"]),
                }
            )

    if not grouped_rows or not fragment_rows:
        raise ValueError(f"No FigStep-Pro annotations found in {shard_path}")

    group_rows = [grouped_rows[index] for index in sorted(grouped_rows)]
    fragment_rows.sort(
        key=lambda row: (int(row["group_index"]), int(row["fragment_index"]))
    )
    return group_rows, fragment_rows


def validate_templates(
    group_rows: list[dict[str, str]],
    fragment_rows: list[dict[str, str]],
    archive_groups: dict[int, list[tuple[int, str]]],
    extract_root: Path,
    project_root: Path,
    annotation_source: str,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    if not group_rows or not fragment_rows:
        raise ValueError(f"No annotations found in {annotation_source}")
    if tuple(group_rows[0]) != GROUP_FIELDS:
        raise ValueError(f"Unexpected group annotation fields in {annotation_source}")
    if tuple(fragment_rows[0]) != FRAGMENT_FIELDS:
        raise ValueError(f"Unexpected fragment annotation fields in {annotation_source}")
    if len(group_rows) != 50 or len(fragment_rows) != 181:
        raise ValueError(
            f"Unexpected template counts: groups={len(group_rows)}, "
            f"fragments={len(fragment_rows)}"
        )
    group_indices = {int(row["group_index"]) for row in group_rows}
    if group_indices != set(archive_groups):
        raise ValueError("Group template indices do not match the archive")
    expected_members = {name for members in archive_groups.values() for _, name in members}
    actual_members = {row["archive_member"] for row in fragment_rows}
    if actual_members != expected_members:
        raise ValueError("Fragment template members do not match the archive")
    for row in fragment_rows:
        expected_path = extract_root.joinpath(*PurePosixPath(row["archive_member"]).parts)
        expected_relative = expected_path.relative_to(project_root).as_posix()
        if row["asset_path"] != expected_relative:
            raise ValueError(
                f"Fragment template path mismatch for {row['archive_member']}: "
                f"{row['asset_path']} != {expected_relative}"
            )
    return group_rows, fragment_rows


def detect_revision(source_root: Path) -> str | None:
    head_path = source_root / ".git/HEAD"
    if not head_path.is_file():
        return None
    head = head_path.read_text(encoding="utf-8").strip()
    if head.startswith("ref: "):
        reference_path = source_root / ".git" / head.removeprefix("ref: ")
        return (
            reference_path.read_text(encoding="utf-8").strip()
            if reference_path.is_file()
            else None
        )
    return head


def build_record(
    group: dict[str, str],
    fragment: dict[str, str],
    project_root: Path,
    revision: str | None,
) -> dict[str, Any]:
    group_index = int(fragment["group_index"])
    fragment_index = int(fragment["fragment_index"])
    asset_path = project_root / fragment["asset_path"]
    if not asset_path.is_file():
        raise FileNotFoundError(f"Missing extracted fragment: {asset_path}")
    width, height, color_mode, bit_depth = png_properties(asset_path)
    transcript_value = fragment["fragment_transcript"].strip()
    has_transcript = bool(transcript_value and transcript_value != PLACEHOLDER)
    mapping_verified = group["mapping_status"].strip().lower() == VERIFIED
    group_transcript = group["group_transcript"].strip()
    group_has_transcript = bool(group_transcript and group_transcript != PLACEHOLDER)
    annotation_complete = has_transcript and group_has_transcript and mapping_verified
    exclusion_reasons = []
    if not has_transcript:
        exclusion_reasons.append("manual_fragment_transcription_pending")
    if not group_has_transcript:
        exclusion_reasons.append("manual_group_transcription_pending")
    if not mapping_verified:
        exclusion_reasons.append("group_mapping_unverified")

    sample_id = f"figstep_pro:group:{group_index:03d}:fragment:{fragment_index:03d}"
    return {
        "schema_version": SCHEMA_VERSION,
        "sample_id": sample_id,
        "asset": {
            "path": fragment["asset_path"],
            "sha256": sha256_file(asset_path),
            "media_type": "image/png",
            "format": "png",
            "width": width,
            "height": height,
            "color_mode": color_mode,
            "bit_depth": bit_depth,
            "bytes": asset_path.stat().st_size,
        },
        "source": {
            "dataset_id": DATASET_ID,
            "upstream_id": fragment["archive_member"],
            "repository": UPSTREAM_REPOSITORY,
            "revision": revision,
            "split": "evaluation",
            "license_spdx": "MIT",
        },
        "group": {
            "content_group_id": f"figstep_pro:group:{group_index:03d}",
            "content_basis": "ordered_fragment_group",
            "variant": "figstep_pro_fragment",
            "parent_sample_id": group["parent_sample_id"],
        },
        "visual": {
            "scene_type": "text_only",
            "text_layout": "split_text_fragment",
            "challenge_tags": [
                "figstep_pro",
                "cross_image_reconstruction",
                "fragmented_text",
            ],
            "generation_type": "rendered",
        },
        "ocr": {
            "has_ground_truth_text": has_transcript,
            "transcript_verbatim": transcript_value if has_transcript else "",
            "transcript_normalized": (
                normalize_transcript(transcript_value) if has_transcript else ""
            ),
            "scope": "all_visible_text" if has_transcript else "none",
            "languages": ["en"] if has_transcript else [],
            "scripts": ["Latn"] if has_transcript else [],
            "reading_order_known": has_transcript,
            "regions": None,
            "annotation": {
                "provenance": "manual" if has_transcript else "manual_placeholder",
                "quality": "silver" if has_transcript else "unlabeled",
                "verified": False,
            },
        },
        "security": {
            "attack_family": "visual_jailbreak",
            "injection_techniques": ["figstep_pro", "fragmented_typographic_prompt"],
            "injection_type": "cross_image_visual",
            "risk_category": group["category_name"],
            "contains_injection_instruction": True,
            "contains_harmful_instruction": True,
        },
        "eligibility": {
            "ocr_eval": annotation_complete,
            "evaluation_mode": (
                "fragment_transcription" if annotation_complete else "manual_annotation_pending"
            ),
            "training": True,
            "exclusion_reasons": exclusion_reasons,
        },
        "rights": {
            "commercial_use": True,
            "training_use": True,
            "attribution_required": True,
            "usage_notes": "Repository and released dataset are provided under the MIT license.",
        },
        "source_specific": {
            "archive_path": "datasets/external/FigStep/data/images/FigStep-Pro/sub-figures.zip",
            "archive_member": fragment["archive_member"],
            "group_index": group_index,
            "fragment_index": fragment_index,
            "fragment_count": int(fragment["fragment_count"]),
            "group_transcript": group_transcript if group_has_transcript else PLACEHOLDER,
            "mapping_status": group["mapping_status"],
            "category_id": int(group["category_id"]),
            "task_id": int(group["task_id"]),
            "category_name": group["category_name"],
            "question": group["question"],
            "instruction": group["instruction"],
            "benign_template": group["benign_template"],
            "system_prompt": None,
            "user_input_text": "Concatenate the ordered image fragments and use their combined text for the placeholder in the accompanying instruction.",
            "judge_question": None,
            "manual_notes": {
                "group": group["notes"],
                "fragment": fragment["notes"],
            },
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
    project_root = Path(__file__).resolve().parents[2]
    source_root = args.source_root.resolve()
    archive_path = source_root / "data/images/FigStep-Pro/sub-figures.zip"
    groups = archive_members(archive_path)
    extract_root = (
        args.extract_root
        if args.extract_root is not None
        else source_root / "data/images/FigStep-Pro/sub-figures"
    ).resolve()
    extract_fragments(archive_path, extract_root, groups)
    manual_root = args.manual_root.resolve()
    groups_path = manual_root / "figstep_pro_groups.csv"
    fragments_path = manual_root / "figstep_pro_fragments.csv"
    if groups_path.is_file() and fragments_path.is_file():
        group_rows = load_csv(groups_path)
        fragment_rows = load_csv(fragments_path)
        annotation_source = f"{groups_path} and {fragments_path}"
    elif not groups_path.exists() and not fragments_path.exists() and args.output.is_file():
        group_rows, fragment_rows = templates_from_source_shard(args.output.resolve())
        annotation_source = str(args.output.resolve())
    else:
        groups_path, fragments_path = create_templates_if_missing(
            source_root,
            extract_root,
            manual_root,
            groups,
            project_root,
        )
        group_rows = load_csv(groups_path)
        fragment_rows = load_csv(fragments_path)
        annotation_source = f"{groups_path} and {fragments_path}"
    group_rows, fragment_rows = validate_templates(
        group_rows,
        fragment_rows,
        groups,
        extract_root,
        project_root.resolve(),
        annotation_source,
    )
    groups_by_index = {int(row["group_index"]): row for row in group_rows}
    revision = detect_revision(source_root)
    records = [
        build_record(
            groups_by_index[int(fragment["group_index"])],
            fragment,
            project_root,
            revision,
        )
        for fragment in fragment_rows
    ]
    sample_ids = [record["sample_id"] for record in records]
    if len(sample_ids) != len(set(sample_ids)):
        raise ValueError("Generated FigStep-Pro sample IDs are not unique")
    if not args.validate_only:
        write_jsonl_atomic(records, args.output.resolve())
    complete = sum(record["eligibility"]["ocr_eval"] for record in records)
    mode = "Validated" if args.validate_only else "Wrote"
    print(
        f"{mode} {len(records)} FigStep-Pro fragment records "
        f"({complete} evaluation-ready, {len(records) - complete} pending)."
    )
    print(f"Annotations: {annotation_source}")
    if not args.validate_only:
        print(f"Output: {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
