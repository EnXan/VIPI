"""Compare pinned OCR models on a frozen, source-stratified production workload."""

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import random
import resource
import shutil
import subprocess
import sys
import time

from PIL import Image, ImageDraw, ImageOps

from research.datasets.catalog import Catalog
from research.evaluation.metrics import compare, final_observations, score
from research.experiments.ocr import ocr_screening
from vipi.ocr.engine_pool import EnginePool
from vipi.ocr.models import FILES, MODEL_NAMES, REQUIRED, sha256, validate_model
from vipi.ocr.pipeline import extract
from vipi.ocr.runtime import threads_per_worker
from vipi.ocr.transforms import OCR_PROFILE, production_passes_for_size
from vipi.storage.ocr import write_json

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_RUN = ROOT / "runs/ocr-model-comparison/2026-10-20-round-01"
MODELS = ("ppocr-v5", "ppocr-v6", "tesseract")
SEED = 20261020
PREVIOUS_ROUNDS = tuple(
    ROOT / f"runs/ocr-screening/2026-10-19-round-{number:02d}/manifest.json"
    for number in range(1, 6)
)
SOURCE_FILES = (
    "research/experiments/ocr/ocr_model_comparison.py",
    "research/experiments/ocr/ocr_screening.py",
    "research/datasets/catalog.py",
    "research/evaluation/runner.py",
    "research/evaluation/metrics.py",
    "src/vipi/ocr/engine_pool.py",
    "src/vipi/ocr/engines.py",
    "src/vipi/ocr/merge.py",
    "src/vipi/ocr/model_files.json",
    "src/vipi/ocr/models.py",
    "src/vipi/ocr/pipeline.py",
    "src/vipi/ocr/runtime.py",
    "src/vipi/ocr/transforms.py",
    "src/vipi/ocr/workers.py",
    "src/vipi/storage/events.py",
    "src/vipi/storage/files.py",
    "src/vipi/storage/ocr.py",
)
STRATA = (
    ("textocr", False),
    ("textocr", True),
    ("cyberseceval3_visual_prompt_injection", False),
    ("cyberseceval3_visual_prompt_injection", False),
    ("mm_safetybench", False),
    ("mm_safetybench", False),
    ("typographic_visual_prompt_injection", False),
    ("typographic_visual_prompt_injection", True),
    ("vpi_bench", False),
    ("vpi_bench", False),
)


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def code_hashes():
    return {name: sha256(ROOT / name) for name in SOURCE_FILES}


def library_versions():
    return {
        name: importlib.metadata.version(name)
        for name in ("numpy", "Pillow", "opencv-python", "rapidocr", "onnxruntime")
    }


def old_samples_and_groups():
    samples = [sample for path in PREVIOUS_ROUNDS for sample in read(path)["samples"]]
    old_ids = {sample["id"] for sample in samples}
    old_groups = {
        sample["content_group_id"]
        for sample in samples
        if sample["category"] != "anamorpher"
    }
    return old_ids, old_groups


def choose_samples(catalog):
    old_ids, used_groups = old_samples_and_groups()
    rng = random.Random(SEED)
    selected = []
    for category, filtered in STRATA:
        pool = [
            item
            for item in catalog.items.values()
            if item["category"] == category
            and ("ocr_obfuscation" in item["image"]) == filtered
            and item["id"] not in old_ids
            and item["details"].get("content_group_id")
            and item["details"]["content_group_id"] not in used_groups
            and ocr_screening.split_for(item["details"]["content_group_id"])
            == "development"
        ]
        if category == "textocr":
            pool = [
                item
                for item in pool
                if 5 <= len(item["details"].get("regions", [])) <= 30
            ]
        pool.sort(key=lambda item: item["id"])
        if not pool:
            raise ValueError(f"No eligible images for {category=}, {filtered=}.")
        chosen = rng.choice(pool)
        selected.append(chosen)
        used_groups.add(chosen["details"]["content_group_id"])

    anamorpher = [
        item
        for item in catalog.items.values()
        if item["category"] == "anamorpher"
        and item["id"] not in old_ids
        and item["details"].get("content_group_id") == "anamorpher_payload_blue"
        and ocr_screening.split_for(item["details"]["content_group_id"])
        == "development"
    ]
    by_dimensions = defaultdict(list)
    for item in anamorpher:
        with Image.open(catalog.path(item["id"])) as image:
            by_dimensions[tuple(image.size)].append(item)
    for dimensions in ((3200, 3200), (4368, 4368)):
        pool = sorted(by_dimensions[dimensions], key=lambda item: item["id"])
        if not pool:
            raise ValueError(f"No unused Anamorpher image at {dimensions}.")
        selected.append(rng.choice(pool))
    return selected


def sample_record(catalog, item):
    path = catalog.path(item["id"])
    reference = catalog.reference(item["id"])
    with Image.open(path) as image:
        dimensions = list(image.size)
    passes = production_passes_for_size(*dimensions)
    return {
        "id": item["id"],
        "image": item["image"],
        "sha256": sha256(path),
        "category": item["category"],
        "content_group_id": item["details"]["content_group_id"],
        "dimensions": dimensions,
        "filtered_input": "ocr_obfuscation" in item["image"],
        "reference": reference,
        "planned_passes": [
            {"index": index, "view_id": view.id, "filter": name}
            for index, (view, name) in enumerate(passes, start=1)
        ],
    }


def draw_contact_sheet(directory, samples):
    columns, cell_w, cell_h = 3, 680, 540
    rows = (len(samples) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * cell_w, rows * cell_h), "#eeeeee")
    draw = ImageDraw.Draw(sheet)
    for index, sample in enumerate(samples):
        x, y = index % columns * cell_w, index // columns * cell_h
        draw.text(
            (x + 12, y + 10),
            f"{sample['id']} · {sample['category']} · {sample['dimensions']}",
            fill="black",
        )
        with Image.open(ROOT / sample["image"]) as source:
            preview = ImageOps.contain(source.convert("RGB"), (cell_w - 24, 410))
        sheet.paste(preview, (x + (cell_w - preview.width) // 2, y + 38))
        text = sample["reference"]["text"].replace("\n", " / ")
        draw.multiline_text(
            (x + 12, y + 458),
            f"{sample['reference']['scope']} · {sample['reference']['quality']}\n{text[:170]}",
            fill="black",
            spacing=5,
        )
    sheet.save(directory / "selection-contact-sheet.jpg", quality=90)


def prepare(directory):
    if directory.exists():
        raise ValueError("Choose a new experiment directory; existing runs are immutable.")
    catalog = Catalog(ROOT)
    selected = choose_samples(catalog)
    samples = [sample_record(catalog, item) for item in selected]
    models_dir = ROOT / "models/ocr"
    model_files = {}
    for model in MODELS:
        validate_model(model, models_dir, verify=True)
        model_files[model] = {
            FILES[key]["file"]: FILES[key]["sha256"] for key in REQUIRED[model]
        }
    model_order = list(MODELS)
    random.Random(SEED + 1).shuffle(model_order)
    manifest = {
        "version": 1,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "seed": SEED,
        "models": model_files,
        "model_order": model_order,
        "model_labels": {model: MODEL_NAMES[model] for model in MODELS},
        "backend": "cpu",
        "workers": 1,
        "threads_per_worker": threads_per_worker(1),
        "ocr_profile": OCR_PROFILE,
        "platform": platform.platform(),
        "cpu_count": os.cpu_count(),
        "libraries": library_versions(),
        "code_hashes": code_hashes(),
        "catalog_sha256": sha256(
            ROOT / "research/datasets/data/catalog/ocr/ocr_metadata.json"
        ),
        "selection_report_sha256": sha256(
            ROOT / "research/datasets/data/catalog/ocr/ocr_selection_report.json"
        ),
        "design": {
            "selection": "12 development images, two per each of the six OCR sources; base groups are new relative to transformation rounds 1-5",
            "filter_variants": "one reviewed TextOCR JPEG and one Dagger7164 Gaussian-blur variant are included",
            "anamorpher": "one 3200x3200 and one 4368x4368 blue-payload variant; both share one content group and are not independent payload examples",
            "profile": "same reduced-transforms-v1 production pass schedule for every model; 12 passes when the 2x raster exceeds 8 megapixels, otherwise 13",
            "execution": "CPU, one worker and one reusable engine pool per model process, same sample set and same per-model sample order",
            "resources": "fresh process per model; wall and CPU time include model initialization and all images; Python and external OCR child peak RSS are reported separately",
            "scoring": "existing source-aware reference evaluation; TextOCR uses word regions, target-only scopes stay target-only",
            "limitations": "small development comparison; all source references are Silver except synthetic Anamorpher references; do not treat as an independent final holdout",
        },
        "samples": samples,
    }
    manifest["protocol_sha256"] = hashlib.sha256(
        json.dumps(
            {
                key: manifest[key]
                for key in (
                    "seed",
                    "models",
                    "model_order",
                    "backend",
                    "workers",
                    "threads_per_worker",
                    "ocr_profile",
                    "code_hashes",
                    "samples",
                )
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()
    directory.mkdir(parents=True)
    write_json(directory / "manifest.json", manifest)
    write_json(directory / "reference_audit.json", {})
    draw_contact_sheet(directory, samples)
    print(f"Prepared {len(samples)} images in {directory}")
    for sample in samples:
        print(
            f"{sample['id']} {sample['category']} {sample['dimensions']} "
            f"{sample['reference']['quality']} {len(sample['planned_passes'])} passes"
        )


def verify(directory):
    manifest = read(directory / "manifest.json")
    if manifest["code_hashes"] != code_hashes():
        raise ValueError("Research or OCR source changed; prepare a new experiment.")
    protocol = hashlib.sha256(
        json.dumps(
            {
                key: manifest[key]
                for key in (
                    "seed",
                    "models",
                    "model_order",
                    "backend",
                    "workers",
                    "threads_per_worker",
                    "ocr_profile",
                    "code_hashes",
                    "samples",
                )
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()
    if manifest["protocol_sha256"] != protocol:
        raise ValueError("Frozen comparison protocol changed.")
    for model, files in manifest["models"].items():
        for filename, expected in files.items():
            if sha256(ROOT / "models/ocr" / filename) != expected:
                raise ValueError(f"Model changed: {filename}")
    for sample in manifest["samples"]:
        if sha256(ROOT / sample["image"]) != sample["sha256"]:
            raise ValueError(f"Image changed: {sample['id']}")
    audit = read(directory / "reference_audit.json")
    status_path = directory / "run_status.json"
    if status_path.exists():
        status = read(status_path)
        if status.get("reference_audit_sha256") != sha256(
            directory / "reference_audit.json"
        ):
            raise ValueError("Reference audit changed after the OCR run started.")
    if set(audit) != {sample["id"] for sample in manifest["samples"]}:
        raise ValueError("Review every selected image and reference before inference.")
    if any(record.get("status") not in {"reviewed", "excluded"} for record in audit.values()):
        raise ValueError("Each reference review must be marked reviewed or excluded.")
    if any(record["status"] == "excluded" for record in audit.values()):
        raise ValueError("Regenerate the frozen sample set after excluding an image.")
    return manifest


def score_result(reference, result):
    """Use the reference matcher without requiring unplanned effect baselines."""
    per_step, union = {}, set()
    for step in result["variants"]:
        matched_score, _, matched = compare(reference, step["text"], step["regions"])
        per_step[step["id"]] = matched_score
        union.update(matched)
    final_regions = (
        result["regions"]
        if reference["reading_order_known"]
        else final_observations(result["regions"], result["variants"])
    )
    final_score, expected, final_matched = compare(
        reference, result["text"], final_regions
    )
    best = max(
        result["variants"],
        key=lambda step: (per_step[step["id"]]["matched"], -step["index"]),
    )
    best_score = per_step[best["id"]]
    detection = (
        final_score
        if reference["reading_order_known"]
        and final_score["matched"] > best_score["matched"]
        else best_score
        if reference["reading_order_known"]
        else score(expected, union | final_matched)
    )
    return {
        "valid": detection["valid"],
        "method": "ordered_tokens"
        if reference["reading_order_known"]
        else "word_regions",
        "detection": detection,
        "final": final_score,
        "original": per_step[result["variants"][0]["id"]],
        "best_step_id": best["id"],
        "steps": per_step,
    }


def run_model(directory, model):
    manifest = verify(directory)
    if model not in MODELS:
        raise ValueError(f"Unsupported comparison model: {model}")
    output = directory / "results" / f"{model}.json"
    if output.exists():
        raise ValueError(f"Model result already exists: {model}")
    output.parent.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    scratch = directory / "scratch" / model
    scratch.mkdir(parents=True, exist_ok=True)
    samples = []
    with EnginePool(model, ROOT / "models/ocr", 1, "cpu") as pool:
        for index, sample in enumerate(manifest["samples"], start=1):
            print(f"{model}: image {index}/{len(manifest['samples'])} {sample['id']}", flush=True)
            result = extract(
                ROOT / sample["image"],
                model,
                models_dir=ROOT / "models/ocr",
                runs_dir=scratch,
                workers=1,
                backend="cpu",
                engine_pool=pool,
            )
            evaluation = score_result(sample["reference"], result)
            run_directory = scratch / result["run_id"]
            samples.append(
                {
                    "id": sample["id"],
                    "category": sample["category"],
                    "content_group_id": sample["content_group_id"],
                    "dimensions": sample["dimensions"],
                    "passes": len(result["variants"]),
                    "elapsed_seconds": result["elapsed_seconds"],
                    "ocr_seconds": sum(
                        step["timing"]["ocr_seconds"] for step in result["variants"]
                    ),
                    "evaluation": evaluation,
                    "text": result["text"],
                    "variants": [
                        {
                            key: value
                            for key, value in step.items()
                            if key != "image"
                        }
                        for step in result["variants"]
                    ],
                }
            )
            write_json(
                output,
                {
                    "model": model,
                    "samples_completed": len(samples),
                    "samples": samples,
                },
            )
            shutil.rmtree(run_directory)

    self_usage = resource.getrusage(resource.RUSAGE_SELF)
    child_usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    result = {
        "model": model,
        "label": MODEL_NAMES[model],
        "elapsed_seconds": time.perf_counter() - started,
        "user_cpu_seconds": self_usage.ru_utime + child_usage.ru_utime,
        "system_cpu_seconds": self_usage.ru_stime + child_usage.ru_stime,
        "python_peak_resident_bytes": self_usage.ru_maxrss
        * (1 if sys.platform == "darwin" else 1024),
        "ocr_child_peak_resident_bytes": child_usage.ru_maxrss
        * (1 if sys.platform == "darwin" else 1024),
        "samples": samples,
    }
    write_json(output, result)
    write_json(directory / "scratch" / model / "resources.json", {
        key: value for key, value in result.items() if key != "samples"
    })
    print(f"Completed {model}: {result['elapsed_seconds']:.1f}s", flush=True)


def aggregate(manifest, model_result):
    samples = model_result["samples"]
    expected = sum(item["evaluation"]["detection"]["total"] for item in samples)
    matched = sum(item["evaluation"]["detection"]["matched"] for item in samples)
    final_expected = sum(item["evaluation"]["final"]["total"] for item in samples)
    final_matched = sum(item["evaluation"]["final"]["matched"] for item in samples)
    categories = defaultdict(lambda: {"images": 0, "matched": 0, "total": 0, "valid": 0})
    for item in samples:
        evaluation = item["evaluation"]
        category = categories[item["category"]]
        category["images"] += 1
        category["matched"] += evaluation["detection"]["matched"]
        category["total"] += evaluation["detection"]["total"]
        category["valid"] += int(evaluation["valid"])
    warm = [item["elapsed_seconds"] for item in samples[1:]]
    return {
        "model": model_result["model"],
        "label": model_result["label"],
        "images_valid": sum(item["evaluation"]["valid"] for item in samples),
        "images_total": len(samples),
        "detection_matched": matched,
        "detection_total": expected,
        "detection_coverage": matched / expected if expected else 0,
        "final_matched": final_matched,
        "final_total": final_expected,
        "final_coverage": final_matched / final_expected if final_expected else 0,
        "batch_elapsed_seconds": model_result.get(
            "controller_elapsed_seconds", model_result["elapsed_seconds"]
        ),
        "elapsed_per_image_seconds": model_result.get(
            "controller_elapsed_seconds", model_result["elapsed_seconds"]
        ) / len(samples),
        "median_warm_image_seconds": sorted(warm)[len(warm) // 2] if warm else None,
        "mean_ocr_seconds_per_pass": sum(item["ocr_seconds"] for item in samples)
        / sum(item["passes"] for item in samples),
        "passes": sum(item["passes"] for item in samples),
        "user_cpu_seconds": model_result["user_cpu_seconds"],
        "system_cpu_seconds": model_result["system_cpu_seconds"],
        "python_peak_resident_bytes": model_result["python_peak_resident_bytes"],
        "ocr_child_peak_resident_bytes": model_result["ocr_child_peak_resident_bytes"],
        "categories": dict(categories),
        "sample_quality": {
            "anamorpher_content_groups": len({
                item["content_group_id"]
                for item in samples
                if item["category"] == "anamorpher"
            }),
            "source_reference_scope": "see frozen manifest per image",
        },
    }


def report(directory):
    manifest = verify(directory)
    summaries = []
    for model in manifest["model_order"]:
        path = directory / "results" / f"{model}.json"
        if not path.is_file():
            raise ValueError(f"Missing completed model results: {model}")
        data = read(path)
        if len(data["samples"]) != len(manifest["samples"]):
            raise ValueError(f"Incomplete model results: {model}")
        summaries.append(aggregate(manifest, data))
    write_json(directory / "report.json", {
        "manifest_sha256": sha256(directory / "manifest.json"),
        "protocol_sha256": manifest["protocol_sha256"],
        "models": summaries,
    })
    lines = [
        "# OCR model comparison — round 1",
        "",
        "Same 12 frozen images and `reduced-transforms-v1` schedule for all models. CPU, one worker; each model reuses one engine across its batch.",
        "",
        "| Model | Detection coverage | Final coverage | Images fully covered | Batch time | Warm median/image | Peak Python RSS | Peak OCR-child RSS |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for item in summaries:
        lines.append(
            f"| {item['label']} | {item['detection_matched']}/{item['detection_total']} ({item['detection_coverage']:.1%}) | "
            f"{item['final_matched']}/{item['final_total']} ({item['final_coverage']:.1%}) | "
            f"{item['images_valid']}/{item['images_total']} | {item['batch_elapsed_seconds']:.1f}s | "
            f"{item['median_warm_image_seconds']:.1f}s | {item['python_peak_resident_bytes'] / 1024**2:.0f} MiB | "
            f"{item['ocr_child_peak_resident_bytes'] / 1024**2:.0f} MiB |"
        )
    lines += [
        "",
        "Detection coverage is the source-aware token/region recall available across the transformed views; final coverage is the assembled OCR result. References are Silver except for synthetic Anamorpher references. The two Anamorpher images share one payload group. This is a small development comparison, not an independent final validation.",
        "",
        "Per-source matched/total counts are recorded in `report.json`; per-image and per-pass readings, timing, and exact model outputs are in `results/`.",
    ]
    (directory / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


def run(directory):
    manifest = verify(directory)
    status_path = directory / "run_status.json"
    if status_path.exists():
        raise ValueError("This experiment was already started; inspect its partial results.")
    write_json(status_path, {
        "state": "running",
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "model_order": manifest["model_order"],
        "reference_audit_sha256": sha256(directory / "reference_audit.json"),
    })
    try:
        for model in manifest["model_order"]:
            print(f"Starting {MODEL_NAMES[model]}", flush=True)
            started = time.perf_counter()
            child = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "research.experiments.ocr.ocr_model_comparison",
                    "_model",
                    str(directory),
                    model,
                ],
                cwd=ROOT,
            )
            _, status, usage = os.wait4(child.pid, 0)
            child.returncode = os.waitstatus_to_exitcode(status)
            if child.returncode:
                raise RuntimeError(f"{model} comparison process failed with {child.returncode}.")
            model_result_path = directory / "results" / f"{model}.json"
            model_result = read(model_result_path)
            model_result["controller_elapsed_seconds"] = time.perf_counter() - started
            write_json(model_result_path, model_result)
            write_json(directory / "scratch" / model / "parent_resources.json", {
                "controller_elapsed_seconds": model_result["controller_elapsed_seconds"],
                "controller_user_cpu_seconds": usage.ru_utime,
                "controller_system_cpu_seconds": usage.ru_stime,
            })
        report(directory)
    except Exception as error:
        previous_status = read(status_path)
        write_json(status_path, {
            "state": "failed",
            "error": str(error),
            "failed_utc": datetime.now(timezone.utc).isoformat(),
            "reference_audit_sha256": previous_status["reference_audit_sha256"],
        })
        raise
    write_json(status_path, {
        "state": "completed",
        "completed_utc": datetime.now(timezone.utc).isoformat(),
        "model_order": manifest["model_order"],
        "reference_audit_sha256": sha256(directory / "reference_audit.json"),
    })


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "run", "report", "_model"))
    parser.add_argument("directory", nargs="?", type=Path, default=DEFAULT_RUN)
    parser.add_argument("model", nargs="?", choices=MODELS)
    args = parser.parse_args(argv)
    directory = args.directory.resolve()
    if args.command == "prepare":
        prepare(directory)
    elif args.command == "run":
        run(directory)
    elif args.command == "report":
        report(directory)
    else:
        if not args.model:
            parser.error("_model requires a model name")
        run_model(directory, args.model)


if __name__ == "__main__":
    main()
