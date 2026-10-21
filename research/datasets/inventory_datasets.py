#!/usr/bin/env python3
"""Build a reproducible CSV inventory of the locally available datasets."""

from __future__ import annotations

import csv
import json
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Sequence


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".tif", ".tiff"}
IGNORED_PARTS = {".git", ".cache", "__pycache__"}

OCR_DATASET_SELECTION = {
    "anamorpher": {
        "ocr_status": "generated_scaling_challenge",
        "next_action": "Evaluate payload after its declared downscale; inspect the generation manifest and failed controls.",
    },
    "textocr": {
        "ocr_status": "usable_silver_word_regions",
        "next_action": "Evaluate annotated words; ignore '.' regions and do not assume a global reading order.",
    },
    "cyberseceval3_visual_prompt_injection": {
        "ocr_status": "usable_silver",
        "next_action": "Evaluate source-declared image_text references; judge-only CAPTCHA targets are excluded.",
    },
    "mm_safetybench": {
        "ocr_status": "usable_silver",
        "next_action": "Verify Key Phrase annotations against rendered text and preserve target-region scoring for SD_TYPO.",
    },
    "typographic_visual_prompt_injection": {
        "ocr_status": "usable_silver",
        "next_action": "Verify rendered text, line wrapping, and text regions for all three variants.",
    },
    "vpi_bench": {
        "ocr_status": "usable_silver_target_only",
        "planned_case_count": 227,
        "available_ocr_images": 190,
        "next_action": "Evaluate reconstructed source-declared target text; other UI text is outside reference coverage.",
    },
}


@dataclass(frozen=True)
class DatasetSpec:
    dataset_id: str
    name: str
    local_path: str
    source_type: str
    primary_paths: tuple[str, ...]
    annotation_files: tuple[str, ...]
    logical_count: Callable[[Path], int | None]
    license_name: str
    training_use: str
    ocr_ground_truth: str
    ocr_eval_tier: str
    recommended_action: str
    source_url: str
    notes: str = ""


def iter_files(root: Path) -> Iterable[Path]:
    if not root.exists():
        return
    for path in root.rglob("*"):
        if not path.is_file() or any(part in IGNORED_PARTS for part in path.parts):
            continue
        yield path


def count_images(root: Path) -> int:
    return sum(path.suffix.lower() in IMAGE_EXTENSIONS for path in iter_files(root))


def count_primary_images(project_root: Path, paths: tuple[str, ...]) -> int:
    return sum(count_images(project_root / path) for path in paths)


def count_json_array(path: Path) -> int:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    return len(value)


def count_json_object_records(path: Path) -> int:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    return len(value)


def count_csv_rows(path: Path, header: bool = True) -> int:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        count = sum(1 for _ in csv.reader(handle))
    return max(0, count - int(header))


def count_json_files(path: Path) -> int:
    return sum(1 for item in iter_files(path) if item.suffix.lower() == ".json")


def count_jsonl(path: Path) -> int:
    if not path.is_file():
        return 0
    with path.open(encoding="utf-8") as handle:
        return sum(bool(line.strip()) for line in handle)


def count_unique_jsonl_ids(path: Path) -> int | None:
    if not path.is_file():
        return None
    with path.open(encoding="utf-8") as handle:
        return len({json.loads(line)["id"] for line in handle if line.strip()})


def catalog_stats(project_root: Path) -> tuple[dict[str, int], dict[str, int], dict[str, int]]:
    """Count catalog records by source dataset, including multi-shard imports."""
    metadata = project_root / "research/datasets/data/catalog/ocr/ocr_metadata.json"
    if metadata.is_file():
        counts: dict[str, int] = {}
        for record in json.loads(metadata.read_text(encoding="utf-8")):
            dataset_id = record["category"]
            counts[dataset_id] = counts.get(dataset_id, 0) + 1
        return counts, {}, counts.copy()
    counts: dict[str, int] = {}
    pending_annotations: dict[str, int] = {}
    ocr_eval_counts: dict[str, int] = {}
    source_dir = project_root / "research/datasets/data/catalog/sources"
    for shard in sorted(source_dir.glob("*.jsonl")):
        with shard.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                    dataset_id = record["source"]["dataset_id"]
                except (json.JSONDecodeError, KeyError, TypeError) as exc:
                    raise ValueError(f"Invalid catalog record in {shard}:{line_number}") from exc
                counts[dataset_id] = counts.get(dataset_id, 0) + 1
                if record.get("eligibility", {}).get("ocr_eval"):
                    ocr_eval_counts[dataset_id] = ocr_eval_counts.get(dataset_id, 0) + 1
                if record.get("eligibility", {}).get("evaluation_mode") == "manual_annotation_pending":
                    pending_annotations[dataset_id] = pending_annotations.get(dataset_id, 0) + 1
    return counts, pending_annotations, ocr_eval_counts


def zip_image_count(root: Path) -> int:
    total = 0
    for archive in (path for path in iter_files(root) if path.suffix.lower() == ".zip"):
        with zipfile.ZipFile(archive) as handle:
            total += sum(Path(name).suffix.lower() in IMAGE_EXTENSIONS for name in handle.namelist())
    return total


def total_size(root: Path) -> int:
    return sum(path.stat().st_size for path in iter_files(root))


def human_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < 1024 or unit == "TiB":
            return f"{value:.1f} {unit}"
        value /= 1024
    raise AssertionError("unreachable")


def extension_summary(root: Path) -> str:
    extensions = sorted(
        {path.suffix.lower().lstrip(".") for path in iter_files(root) if path.suffix}
    )
    return ";".join(extensions)


def phantom_status(root: Path) -> str:
    required_files = ("metadata.jsonl", "behaviours.jsonl")
    required_dirs = ("BAP", "CSDJ", "FC_ATTACK", "IDEATOR", "MML")
    if all((root / name).exists() for name in (*required_files, *required_dirs)):
        return "complete"
    return "in_progress_or_incomplete"


def dataset_status(spec: DatasetSpec, root: Path) -> str:
    if not root.exists():
        return "missing"
    if spec.dataset_id == "phantom":
        return phantom_status(root)
    if spec.dataset_id == "typographic_visual_prompt_injection" and not (root / "images").exists():
        return "archive_only"
    return "present"


def annotation_count(spec: DatasetSpec, project_root: Path) -> int:
    if spec.dataset_id == "anamorpher":
        path = project_root / spec.annotation_files[0]
        return len(json.loads(path.read_text())["records"]) if path.exists() else 0
    if spec.dataset_id == "textocr":
        path = project_root / spec.annotation_files[0]
        if not path.is_file():
            return 0
        data = json.loads(path.read_text(encoding="utf-8"))
        return sum(annotation["utf8_string"].strip() not in {"", "."}
                   for annotation in data["anns"].values())
    if spec.dataset_id == "prism":
        return count_csv_rows(project_root / spec.annotation_files[0]) + count_csv_rows(
            project_root / spec.annotation_files[1], header=False
        )
    if spec.dataset_id == "mm_safetybench":
        directory = project_root / "research/datasets/data/external/MM-SafetyBench/data/processed_questions"
        return sum(count_json_object_records(path) for path in directory.glob("*.json"))
    if spec.dataset_id == "figstep":
        return sum(count_csv_rows(project_root / path) for path in spec.annotation_files)
    if spec.dataset_id == "cyberseceval3_visual_prompt_injection":
        return count_json_array(project_root / spec.annotation_files[0])
    if spec.dataset_id == "vpi_bench":
        return count_json_files(
            project_root / "research/datasets/data/external/VPI-Bench/vpi-bench/testcases/main_benchmark"
        )
    if spec.dataset_id == "typographic_visual_prompt_injection":
        return count_csv_rows(project_root / spec.annotation_files[0])
    if spec.dataset_id == "phantom":
        return count_jsonl(project_root / "research/datasets/data/external/it4lia/PHANTOM/metadata.jsonl")
    return 0


def specs() -> tuple[DatasetSpec, ...]:
    fixed = lambda value: lambda _root: value
    return (
        DatasetSpec(
            "textocr", "TextOCR", "research/datasets/data/external/text-ocr", "downloaded_dataset",
            ("research/datasets/data/external/text-ocr/train_images",),
            ("research/datasets/data/external/text-ocr/TextOCR_0.1_train.json",),
            fixed(21778), "CC-BY-4.0", "not_assessed_for_training",
            "source_word_transcripts_and_polygons", "core_and_challenge",
            "Reserve 50% of the OCR sample for randomly selected natural scene images.",
            "https://textvqa.org/textocr/dataset/",
            "Local train annotations cover 21,778 images; 29 have no transcribed words. '.' marks unreadable/non-English regions. Word annotation order is not guaranteed reading order. Extra local images without these annotations are not sampled.",
        ),
        DatasetSpec(
            "prism",
            "PRISM Adversarial Images",
            "research/datasets/data/external/Zonghao2025/PRISM_Adversarial_Image_Dataset",
            "huggingface_dataset",
            (
                "research/datasets/data/external/Zonghao2025/PRISM_Adversarial_Image_Dataset/figstep_img",
                "research/datasets/data/external/Zonghao2025/PRISM_Adversarial_Image_Dataset/mmsafetybench_img",
            ),
            (
                "research/datasets/data/external/Zonghao2025/PRISM_Adversarial_Image_Dataset/figstep.csv",
                "research/datasets/data/external/Zonghao2025/PRISM_Adversarial_Image_Dataset/mmsafetybench.csv",
            ),
            fixed(2180),
            "Apache-2.0",
            "license_allows_training",
            "not_applicable_for_current_ocr_evaluation",
            "exclude_text_injection_ocr",
            "Exclude from the current OCR evaluation; retain only as adversarial-image research data.",
            "https://huggingface.co/datasets/Zonghao2025/PRISM_Adversarial_Image_Dataset",
            "The available semantic prompt metadata is not suitable OCR ground truth for this evaluation.",
        ),
        DatasetSpec(
            "visinject",
            "VisInject",
            "research/datasets/data/external/jeffliulab/visinject",
            "huggingface_dataset",
            (
                "research/datasets/data/external/jeffliulab/visinject/experiments",
                "research/datasets/data/external/jeffliulab/visinject/succeed_injection_examples",
            ),
            ("research/datasets/data/external/jeffliulab/visinject/succeed_injection_examples/manifest.json",),
            fixed(147),
            "CC-BY-4.0",
            "allowed_with_attribution",
            "not_applicable_pixel_perturbation",
            "exclude_text_injection_ocr",
            "Exclude from text-injection OCR evaluation; retain for later MLL pixel-perturbation work.",
            "https://huggingface.co/datasets/jeffliulab/visinject",
            "Pixel-level adversarial attack, not rendered text injection; target_phrase is the intended VLM response, not image text.",
        ),
        DatasetSpec(
            "visual_adversarial_examples_jailbreak",
            "Visual Adversarial Examples Jailbreak LLMs",
            "research/datasets/data/external/Visual-Adversarial-Examples-Jailbreak-Large-Language-Models",
            "git_repository",
            ("research/datasets/data/external/Visual-Adversarial-Examples-Jailbreak-Large-Language-Models/adversarial_images",),
            (),
            fixed(5),
            "unknown",
            "review_required",
            "none",
            "exclude_initially",
            "Keep the five attack images as research artifacts, not OCR ground truth.",
            "https://github.com/Unispac/Visual-Adversarial-Examples-Jailbreak-Large-Language-Models",
        ),
        DatasetSpec(
            "phantom",
            "PHANTOM",
            "research/datasets/data/external/it4lia/PHANTOM",
            "huggingface_dataset",
            tuple(
                f"research/datasets/data/external/it4lia/PHANTOM/{strategy}"
                for strategy in ("BAP", "IDEATOR", "MML", "FC_ATTACK", "CSDJ")
            ),
            (
                "research/datasets/data/external/it4lia/PHANTOM/metadata.jsonl",
                "research/datasets/data/external/it4lia/PHANTOM/behaviours.jsonl",
            ),
            lambda root: count_unique_jsonl_ids(root / "metadata.jsonl"),
            "CC-BY-4.0",
            "allowed_with_attribution",
            "no_exact_image_transcript",
            "exclude_current_ocr_catalog",
            "Keep outside active OCR metadata; retain the archival shard and upstream data for provenance.",
            "https://huggingface.co/datasets/it4lia/PHANTOM",
            "48,575 image-turn metadata rows; 23 IDEATOR references are absent from the release manifest.",
        ),
        DatasetSpec(
            "mm_safetybench",
            "MM-SafetyBench",
            "research/datasets/data/external/MM-SafetyBench",
            "git_repository_plus_images",
            ("research/datasets/data/external/MM-SafetyBench/MM-SafetyBench(imgs)",),
            tuple(
                f"research/datasets/data/external/MM-SafetyBench/data/processed_questions/{name}.json"
                for name in (
                    "01-Illegal_Activitiy",
                    "02-HateSpeech",
                    "03-Malware_Generation",
                    "04-Physical_Harm",
                    "05-EconomicHarm",
                    "06-Fraud",
                    "07-Sex",
                    "08-Political_Lobbying",
                    "09-Privacy_Violence",
                    "10-Legal_Opinion",
                    "11-Financial_Advice",
                    "12-Health_Consultation",
                    "13-Gov_Decision",
                )
            ),
            fixed(1680),
            "CC-BY-NC-4.0",
            "noncommercial_only",
            "source_declared_key_phrase_target_region",
            "core_and_challenge",
            "Sample TYPO and SD_TYPO from matched question groups; SD backgrounds and orphan images are excluded.",
            "https://github.com/isXinLiu/MM-SafetyBench",
            "OCR reference covers the rendered Key Phrase only; SD backgrounds may contain other untranscribed text.",
        ),
        DatasetSpec(
            "figstep",
            "FigStep",
            "research/datasets/data/external/FigStep",
            "git_repository",
            (
                "research/datasets/data/external/FigStep/data/images/SafeBench",
                "research/datasets/data/external/FigStep/data/images/SafeBench-Tiny",
            ),
            (
                "research/datasets/data/external/FigStep/data/question/safebench.csv",
                "research/datasets/data/external/FigStep/data/question/SafeBench-Tiny.csv",
            ),
            fixed(600),
            "MIT",
            "license_allows_training",
            "reconstructable_exact_text",
            "exclude_current_ocr_catalog",
            "Excluded from OCR sources by user request; raw files remain in the local inventory.",
            "https://github.com/CryptoAILab/FigStep",
        ),
        DatasetSpec(
            "multimodal_injection",
            "Multimodal Injection",
            "research/datasets/data/external/multimodal_injection",
            "git_repository",
            (
                "research/datasets/data/external/multimodal_injection/original_images",
                "research/datasets/data/external/multimodal_injection/result_images",
            ),
            (),
            fixed(12),
            "MIT",
            "license_allows_training",
            "none",
            "exclude_initially",
            "Demo and result images rather than a labeled OCR dataset.",
            "https://github.com/ebagdasa/multimodal_injection",
        ),
        DatasetSpec(
            "cyberseceval3_visual_prompt_injection",
            "CyberSecEval3 Visual Prompt Injection",
            "research/datasets/data/external/facebook/cyberseceval3-visual-prompt-injection",
            "huggingface_dataset",
            ("research/datasets/data/external/facebook/cyberseceval3-visual-prompt-injection/images",),
            ("research/datasets/data/external/facebook/cyberseceval3-visual-prompt-injection/test_cases.json",),
            fixed(1000),
            "MIT",
            "evaluation_only_by_dataset_card",
            "upstream_image_text",
            "core",
            "Sample existing images with image_text only; exclude 100 judge-only CAPTCHA targets and missing images.",
            "https://huggingface.co/datasets/facebook/cyberseceval3-visual-prompt-injection",
        ),
        DatasetSpec(
            "vpi_bench",
            "VPI-Bench",
            "research/datasets/data/external/VPI-Bench/vpi-bench",
            "huggingface_dataset",
            ("research/datasets/data/external/VPI-Bench/screenshots",),
            ("research/datasets/data/external/VPI-Bench/vpi-bench/main_benchmark.parquet",),
        fixed(306),
        "CC-BY-4.0",
        "not_intended_for_training",
        "source_declared_popup_email_chat_target",
        "core",
        "Sample unique screenshots with source-declared Silver target references; BBC is excluded.",
        "https://huggingface.co/datasets/VPI-Bench/vpi-bench",
            "227 active testcase references map to 190 unique rendered URLs; 79 BBC cases/screenshots are excluded from OCR. The original upstream BBC configurations are retained. 36 remaining popup configurations reference a missing background image; no unreferenced screenshots remain in the active folder.",
        ),
        DatasetSpec(
            "anamorpher",
            "Anamorpher",
            "research/datasets/data/external/anamorpher",
            "git_repository",
            ("research/datasets/data/derived/anamorpher/v1/images",),
            ("research/datasets/data/catalog/ocr/anamorpher_manifest.json",),
            lambda _: count_images(Path(__file__).resolve().parents[2] / "research/datasets/data/derived/anamorpher/v1/images"),
            "Apache-2.0",
            "not_assessed_for_training",
            "synthetic_payload_with_verified_declared_downscale",
            "scaling_attack_challenge",
            "Evaluate the generated challenge using the recorded resampler, target size and target region; keep failed controls separate.",
            "https://github.com/trailofbits/anamorpher",
            "Generated images live under research/datasets/data/derived/anamorpher/v1; the upstream demos are not OCR ground truth. Payload is reference text after declared downscale, not a certified native-resolution transcript.",
        ),
        DatasetSpec(
            "typographic_visual_prompt_injection",
            "Typographic Visual Prompt Injection",
            "research/datasets/data/external/Dagger7164/VisualPromptInjection",
            "huggingface_dataset",
            ("research/datasets/data/external/Dagger7164/VisualPromptInjection/images",),
            ("research/datasets/data/external/Dagger7164/VisualPromptInjection/prompts.csv",),
            fixed(135),
            "MIT",
            "not_intended_for_attack_model_training_by_dataset_card",
            "source_declared_prompt_text",
            "core",
            "Imported 135 images; keep all three styles of each prompt in the same eval split.",
            "https://huggingface.co/datasets/Dagger7164/VisualPromptInjection",
            "45 prompt texts mapped to clean, lowcontrast, and distorted images; line breaks and text regions are not annotated.",
        ),
    )


def build_rows(project_root: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    catalog_counts, pending_annotations, ocr_eval_counts = catalog_stats(project_root)
    for spec in specs():
        root = project_root / spec.local_path
        catalog_record_count = catalog_counts.get(spec.dataset_id, 0)
        pending_annotation_count = pending_annotations.get(spec.dataset_id, 0)
        ocr_eval_count = ocr_eval_counts.get(spec.dataset_id, 0)
        if not catalog_record_count and spec.ocr_eval_tier in {
            "exclude_text_injection_ocr",
            "exclude_initially",
            "exclude_current_ocr_catalog",
        }:
            catalog_status = "excluded_from_current_ocr"
        elif pending_annotation_count:
            catalog_status = "normalized_with_pending_annotations"
        elif catalog_record_count and not ocr_eval_count:
            catalog_status = "normalized_without_ocr_ground_truth"
        elif catalog_record_count:
            catalog_status = "normalized"
        else:
            catalog_status = "pending"
        rows.append(
            {
                "dataset_id": spec.dataset_id,
                "name": spec.name,
                "local_path": spec.local_path,
                "source_type": spec.source_type,
                "download_status": dataset_status(spec, root),
                "logical_case_count": spec.logical_count(root) or "",
                "primary_image_count": count_primary_images(project_root, spec.primary_paths),
                "raster_files_total": count_images(root),
                "images_in_archives": zip_image_count(root),
                "annotation_record_count": annotation_count(spec, project_root),
                "catalog_status": catalog_status,
                "catalog_record_count": catalog_record_count,
                "catalog_pending_annotation_count": pending_annotation_count,
                "catalog_ocr_eval_count": ocr_eval_count,
                "annotation_files": ";".join(spec.annotation_files),
                "size_bytes_excluding_cache_and_git": total_size(root),
                "size_human": human_size(total_size(root)),
                "file_extensions": extension_summary(root),
                "license": spec.license_name,
                "training_use": spec.training_use,
                "ocr_ground_truth": spec.ocr_ground_truth,
                "ocr_eval_tier": spec.ocr_eval_tier,
                "recommended_action": spec.recommended_action,
                "source_url": spec.source_url,
                "notes": spec.notes,
            }
        )
    return rows


def build_ocr_rows(inventory_rows: list[dict[str, object]], project_root: Path) -> list[dict[str, object]]:
    """Build the small, active OCR-dataset overview from the full source inventory."""
    report_path = project_root / "research/datasets/data/catalog/ocr/ocr_selection_report.json"
    if report_path.is_file():
        report = json.loads(report_path.read_text(encoding="utf-8"))
        return [{"dataset_id": dataset_id,
                 "available_ocr_images": report["eligible_counts"][dataset_id],
                 "selected_ocr_images": count}
                for dataset_id, count in report["selected_counts"].items()]
    inventory_by_id = {str(row["dataset_id"]): row for row in inventory_rows}
    rows: list[dict[str, object]] = []
    for dataset_id, selection in OCR_DATASET_SELECTION.items():
        source = inventory_by_id[dataset_id]
        metadata_records = int(source["catalog_record_count"])
        available_images = selection.get(
            "available_ocr_images",
            metadata_records if metadata_records else int(source["primary_image_count"]),
        )
        rows.append(
            {
                "dataset_id": dataset_id,
                "name": source["name"],
                "ocr_status": selection["ocr_status"],
                "planned_case_count": selection.get(
                    "planned_case_count", source["logical_case_count"]
                ),
                "available_ocr_images": available_images,
                "metadata_record_count": metadata_records,
                "ocr_eval_record_count": int(source["catalog_ocr_eval_count"]),
                "in_metadata_jsonl": "yes" if metadata_records else "no",
                "ground_truth_basis": source["ocr_ground_truth"],
                "next_action": selection["next_action"],
            }
        )
    return rows


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main(argv: Sequence[str] | None = None) -> int:
    project_root = Path(__file__).resolve().parents[2]
    inventory_output = project_root / "research/datasets/data/catalog/datasets.csv"
    ocr_output = project_root / "research/datasets/data/catalog/ocr/ocr_datasets.csv"
    inventory_rows = build_rows(project_root)
    ocr_rows = build_ocr_rows(inventory_rows, project_root)
    write_csv(inventory_output, inventory_rows)
    write_csv(ocr_output, ocr_rows)
    print(f"Wrote {len(inventory_rows)} dataset records to {inventory_output}")
    print(f"Wrote {len(ocr_rows)} OCR dataset records to {ocr_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
