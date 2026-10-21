"""Compare OCR models on one raw, held-out image per content group."""

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
import subprocess
import sys
import time

import cv2
from PIL import Image, ImageDraw, ImageOps

from research.datasets.catalog import Catalog
from research.evaluation.metrics import compare
from research.experiments.ocr.ocr_screening import split_for
from vipi.ocr.engines import create_engine
from vipi.ocr.models import FILES, REQUIRED, sha256, validate_model
from vipi.ocr.runtime import prepare_backend, rapid_runtime_params, threads_per_worker
from vipi.ocr.transforms import decode_image
from vipi.storage.ocr import write_json

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_RUN = ROOT / "runs/ocr-model-comparison/2026-10-20-raw-holdout-02"
SEED = 20261020
MODEL_ORDER = ("ppocr-v6-medium", "ppocr-v6-small", "tesseract")
MODEL_LABELS = {
    "ppocr-v6-medium": "PP-OCRv6 · medium",
    "ppocr-v6-small": "PP-OCRv6 · small",
    "tesseract": "Tesseract · English / best",
}
SOURCE_QUOTAS = (
    ("textocr", 10),
    ("cyberseceval3_visual_prompt_injection", 10),
    ("mm_safetybench", 10),
    ("typographic_visual_prompt_injection", 10),
    ("vpi_bench", 10),
)
CODE_FILES = (
    "research/experiments/ocr/ocr_raw_model_comparison.py",
    "research/experiments/ocr/ocr_screening.py",
    "research/datasets/catalog.py",
    "research/evaluation/metrics.py",
    "src/vipi/ocr/engines.py",
    "src/vipi/ocr/model_files.json",
    "src/vipi/ocr/models.py",
    "src/vipi/ocr/runtime.py",
    "src/vipi/ocr/transforms.py",
    "src/vipi/storage/files.py",
    "src/vipi/storage/ocr.py",
)


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def code_hashes():
    return {name: sha256(ROOT / name) for name in CODE_FILES}


def library_versions():
    return {
        name: importlib.metadata.version(name)
        for name in ("numpy", "Pillow", "opencv-python", "rapidocr", "onnxruntime")
    }


def eligible_groups(catalog, category):
    groups = defaultdict(list)
    for item in catalog.items.values():
        if item["category"] != category:
            continue
        group = item.get("details", {}).get("content_group_id")
        if not group or split_for(group) != "holdout":
            continue
        # Use the original catalog image when a filtered sibling exists.
        if "ocr_obfuscation" in item["image"]:
            continue
        if category == "textocr" and not 5 <= len(item["details"].get("regions", [])) <= 30:
            continue
        groups[group].append(item)
    return groups


def choose_samples(catalog, count_per_source, seed):
    rng = random.Random(seed)
    selected = []
    for category, requested in SOURCE_QUOTAS:
        groups = eligible_groups(catalog, category)
        group_ids = sorted(groups)
        rng.shuffle(group_ids)
        if not group_ids:
            raise ValueError(f"No eligible holdout images for {category}.")
        for group in group_ids[: min(count_per_source, requested, len(group_ids))]:
            variants = sorted(groups[group], key=lambda item: item["id"])
            selected.append(rng.choice(variants))
    selected_groups = [item["details"]["content_group_id"] for item in selected]
    if len(selected_groups) != len(set(selected_groups)):
        raise ValueError("The sample contains repeated content groups.")
    return selected


def small_model_files():
    import rapidocr

    model_dir = Path(rapidocr.__file__).resolve().parent / "models"
    names = ("PP-OCRv6_det_small.onnx", "PP-OCRv6_rec_small.onnx")
    paths = {name: model_dir / name for name in names}
    paths[FILES["ch_PP-LCNet_x0_25_textline_ori_cls_mobile"]["file"]] = (
        ROOT
        / "models/ocr"
        / FILES["ch_PP-LCNet_x0_25_textline_ori_cls_mobile"]["file"]
    )
    missing = [str(path) for path in paths.values() if not path.is_file()]
    if missing:
        raise ValueError("Missing PP-OCRv6 small model files: " + ", ".join(missing))
    return paths


def model_file_hashes():
    result = {}
    for key in REQUIRED["ppocr-v6"]:
        path = ROOT / "models/ocr" / FILES[key]["file"]
        validate_model("ppocr-v6", ROOT / "models/ocr", verify=True)
        result[FILES[key]["file"]] = sha256(path)
    for name, path in small_model_files().items():
        result[f"small/{name}"] = sha256(path)
    key = "tesseract-eng"
    result[FILES[key]["file"]] = sha256(ROOT / "models/ocr" / FILES[key]["file"])
    validate_model("tesseract", ROOT / "models/ocr", verify=True)
    return result


def draw_contact_sheets(directory, catalog, samples):
    columns, cell_w, cell_h = 2, 650, 390
    categories = list(dict.fromkeys(item["category"] for item in samples))
    for category in categories:
        items = [item for item in samples if item["category"] == category]
        rows = (len(items) + columns - 1) // columns
        sheet = Image.new("RGB", (columns * cell_w, rows * cell_h), "#eeeeee")
        draw = ImageDraw.Draw(sheet)
        for index, item in enumerate(items):
            x, y = index % columns * cell_w, index // columns * cell_h
            path = catalog.path(item["id"])
            with Image.open(path) as source:
                preview = ImageOps.contain(source.convert("RGB"), (cell_w - 24, 265))
            sheet.paste(preview, (x + (cell_w - preview.width) // 2, y + 25))
            text = item["text"].replace("\n", " / ")
            draw.multiline_text(
                (x + 12, y + 300),
                f"{item['id']} · {item['category']} · {item['details']['content_group_id']}\n"
                f"{item['details'].get('scope', 'source_declared_text')} · "
                f"{item['details'].get('annotation', {}).get('quality', 'silver')}\n"
                f"{text[:150]}",
                fill="black",
                spacing=4,
            )
        filename = f"contact-{category}.jpg"
        sheet.save(directory / filename, quality=90)


def prepare(directory, count_per_source=10, seed=SEED):
    if directory.exists():
        raise ValueError("Choose a new experiment directory; completed runs are immutable.")
    catalog = Catalog(ROOT)
    chosen = choose_samples(catalog, count_per_source, seed)
    samples = []
    for item in chosen:
        path = catalog.path(item["id"])
        reference = catalog.reference(item["id"])
        with Image.open(path) as image:
            dimensions = list(image.size)
        samples.append(
            {
                "id": item["id"],
                "image": item["image"],
                "sha256": sha256(path),
                "category": item["category"],
                "content_group_id": item["details"]["content_group_id"],
                "dimensions": dimensions,
                "filtered_input": False,
                "reference": reference,
            }
        )
    model_hashes = model_file_hashes()
    model_order = list(MODEL_ORDER)
    random.Random(seed + 1).shuffle(model_order)
    manifest = {
        "version": 1,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "seed": seed,
        "count_per_source": count_per_source,
        "models": model_order,
        "model_labels": MODEL_LABELS,
        "model_files_sha256": model_hashes,
        "backend": "cpu",
        "workers": 1,
        "threads": threads_per_worker(1),
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
            "selection": "held-out images, one image per unique content group; source-stratified across all five standard OCR sources",
            "requested_per_source": count_per_source,
            "inputs": "unfiltered catalog images only; no sibling variants are selected",
            "execution": "one direct OCR call on each decoded input image; no VIPI transformation passes, tiles, filters, cross-view merge or ensemble",
            "model_preprocessing": "model-adapter preprocessing remains enabled and is recorded; this isolates OCR models from the VIPI transformation pipeline",
            "scoring": "source-aware reference matching; TextOCR uses annotated word regions; target-only scopes stay target-only",
            "reference_scope": "Silver source references; source-declared target-only scopes remain target-only",
            "limitations": "Anamorpher is excluded because its reference applies only after a declared downscale; Dagger7164 contributes all nine available holdout groups",
        },
        "samples": samples,
    }
    manifest["protocol_sha256"] = hashlib.sha256(
        json.dumps(
            {
                key: manifest[key]
                for key in (
                    "seed",
                    "count_per_source",
                    "models",
                    "model_files_sha256",
                    "backend",
                    "threads",
                    "code_hashes",
                    "samples",
                    "design",
                )
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()
    directory.mkdir(parents=True)
    write_json(directory / "manifest.json", manifest)
    write_json(
        directory / "reference_audit.json",
        {
            sample["id"]: {"status": "pending", "notes": ""}
            for sample in samples
        },
    )
    draw_contact_sheets(directory, catalog, chosen)
    print(f"Prepared {len(samples)} raw images across {len(categories(samples))} sources.")
    for category, count in category_counts(samples).items():
        print(f"{category}: {count}")
    print("Review contact-*.jpg, then mark each reference as reviewed in reference_audit.json.")


def categories(samples):
    return {item["category"] for item in samples}


def category_counts(samples):
    counts = defaultdict(int)
    for item in samples:
        counts[item["category"]] += 1
    return dict(counts)


def protocol_hash(manifest):
    keys = (
        "seed",
        "count_per_source",
        "models",
        "model_files_sha256",
        "backend",
        "threads",
        "code_hashes",
        "samples",
        "design",
    )
    return hashlib.sha256(
        json.dumps({key: manifest[key] for key in keys}, sort_keys=True).encode()
    ).hexdigest()


def verify(directory, require_review=True):
    manifest = read(directory / "manifest.json")
    if manifest["code_hashes"] != code_hashes():
        raise ValueError("Experiment or OCR source changed; prepare a new run.")
    if manifest["protocol_sha256"] != protocol_hash(manifest):
        raise ValueError("Frozen experiment protocol changed.")
    if manifest["model_files_sha256"] != model_file_hashes():
        raise ValueError("One or more model files changed after preparation.")
    for sample in manifest["samples"]:
        if sha256(ROOT / sample["image"]) != sample["sha256"]:
            raise ValueError(f"Image changed: {sample['id']}")
    if require_review:
        audit = read(directory / "reference_audit.json")
        if set(audit) != {sample["id"] for sample in manifest["samples"]}:
            raise ValueError("Review every selected image and reference before inference.")
        if any(entry.get("status") != "reviewed" for entry in audit.values()):
            raise ValueError("Every selected reference must be marked reviewed.")
    return manifest


class V6SmallEngine:
    """Research-only PP-OCRv6 tiny/small adapter matching VIPI's settings."""

    def __init__(self, directory, threads, *, size="small", model_paths=None):
        import cv2
        import numpy as np
        from rapidocr import RapidOCR
        from rapidocr.ch_ppocr_cls import TextClsOutput
        from rapidocr.ch_ppocr_det.utils import DetPreProcess
        from rapidocr.ch_ppocr_rec import TextRecOutput
        from rapidocr.utils.typings import LangDet, LangRec, ModelType, OCRVersion

        class StrictRapidOCR(RapidOCR):
            def run_ocr_steps(self, image, op_record):
                op_record["padding_1"] = {"top": 0, "left": 0}
                detection = self.text_det(image)
                if detection.boxes is None:
                    return detection, None, TextRecOutput(), []
                crops = self.crop_text_regions(image, detection.boxes)
                return detection, None, self.recognize_txt(crops), crops

            def build_final_output(
                self, image, detection, classification, recognition, crops, operations
            ):
                return super().build_final_output(
                    image, detection, TextClsOutput(), recognition, crops, operations
                )

        class RasterPreprocess(DetPreProcess):
            def resize(self, image):
                height, width = image.shape[:2]
                size = (
                    max(32, round(width / 32) * 32),
                    max(32, round(height / 32) * 32),
                )
                return cv2.resize(image, size, interpolation=cv2.INTER_LINEAR)

        if size not in {"tiny", "small"}:
            raise ValueError(f"Unsupported PP-OCRv6 lightweight size: {size}")
        paths = model_paths or small_model_files()
        cls_name = FILES["ch_PP-LCNet_x0_25_textline_ori_cls_mobile"]["file"]
        params = {
            "Global.use_cls": False,
            "Global.use_preprocess_img": False,
            "Global.use_vertical_padding": False,
            "Global.return_word_box": True,
            "Global.text_score": 0.0,
            "Global.log_level": "error",
            "Det.model_path": str(paths[f"PP-OCRv6_det_{size}.onnx"].resolve()),
            "Rec.model_path": str(paths[f"PP-OCRv6_rec_{size}.onnx"].resolve()),
            "Cls.model_path": str(paths[cls_name].resolve()),
            "Det.ocr_version": OCRVersion.PPOCRV6,
            "Det.model_type": getattr(ModelType, size.upper()),
            "Det.lang_type": LangDet.MULTI,
            "Rec.ocr_version": OCRVersion.PPOCRV6,
            "Rec.model_type": getattr(ModelType, size.upper()),
            "Rec.lang_type": LangRec.CH,
            "Cls.ocr_version": OCRVersion.PPOCRV5,
            **rapid_runtime_params("cpu", threads, directory),
        }
        self.ocr = StrictRapidOCR(params=params)
        detector = self.ocr.text_det
        detector.get_preprocess = lambda _: RasterPreprocess(
            mean=detector.mean, std=detector.std
        )
        self.cv2, self.np = cv2, np

    def recognize(self, image):
        result = self.ocr(
            self.cv2.cvtColor(self.np.asarray(image), self.cv2.COLOR_RGB2BGR)
        )
        regions = []
        texts = getattr(result, "txts", None) or ()
        boxes = getattr(result, "boxes", None)
        scores = getattr(result, "scores", None) or ()
        word_lines = getattr(result, "word_results", None) or ()
        if texts and (boxes is None or len(boxes) != len(texts)):
            raise RuntimeError("OCR returned text without matching positions.")
        for index, text in enumerate(texts):
            words = word_lines[index] if index < len(word_lines) else ()
            word_text = "".join("".join(word.split()) for word, _, _ in words)
            if words and word_text == "".join(text.split()):
                regions.extend(
                    {"text": word, "polygon": polygon, "confidence": score}
                    for word, score, polygon in words
                    if word.strip()
                )
            else:
                regions.append(
                    {"text": text, "polygon": boxes[index], "confidence": scores[index]}
                )
        return {"text": "\n".join(texts), "regions": regions}


def make_engine(model, directory, threads):
    cv2.setNumThreads(1)
    if model == "ppocr-v6-medium":
        return create_engine("ppocr-v6", directory, backend="cpu", threads=threads)
    if model == "ppocr-v6-small":
        prepare_backend("cpu")
        return V6SmallEngine(directory, threads)
    if model == "tesseract":
        return create_engine("tesseract", directory, backend="cpu", threads=threads)
    raise ValueError(f"Unknown comparison model: {model}")


def run_model(directory, model):
    manifest = verify(directory)
    if model not in manifest["models"]:
        raise ValueError(f"Model is not part of this run: {model}")
    output = directory / "results" / f"{model}.json"
    if output.exists():
        raise ValueError(f"Results already exist for {model}.")
    output.parent.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    engine_started = time.perf_counter()
    engine = make_engine(model, ROOT / "models/ocr", manifest["threads"])
    initialization_seconds = time.perf_counter() - engine_started
    rows = []
    for index, sample in enumerate(manifest["samples"], start=1):
        print(f"{model}: image {index}/{len(manifest['samples'])} {sample['id']}", flush=True)
        image = decode_image(ROOT / sample["image"])
        image_started = time.perf_counter()
        observed = engine.recognize(image)
        elapsed = time.perf_counter() - image_started
        regions = [
            {"text": item["text"], "input_polygon": item.get("polygon", [])}
            for item in observed["regions"]
        ]
        result, expected, matched = compare(
            sample["reference"], observed["text"], regions
        )
        rows.append(
            {
                "id": sample["id"],
                "category": sample["category"],
                "content_group_id": sample["content_group_id"],
                "elapsed_seconds": elapsed,
                "evaluation": result,
                "text": observed["text"],
                "regions": observed["regions"],
                "expected_tokens": len(expected),
                "matched_tokens": len(matched),
            }
        )
        write_json(
            output,
            {
                "model": model,
                "label": MODEL_LABELS[model],
                "initialization_seconds": initialization_seconds,
                "samples_completed": len(rows),
                "samples": rows,
            },
        )
    self_usage = resource.getrusage(resource.RUSAGE_SELF)
    child_usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    to_bytes = 1 if sys.platform == "darwin" else 1024
    result = {
        "model": model,
        "label": MODEL_LABELS[model],
        "elapsed_seconds": time.perf_counter() - started,
        "initialization_seconds": initialization_seconds,
        "user_cpu_seconds": self_usage.ru_utime + child_usage.ru_utime,
        "system_cpu_seconds": self_usage.ru_stime + child_usage.ru_stime,
        "python_peak_resident_bytes": self_usage.ru_maxrss * to_bytes,
        "ocr_child_peak_resident_bytes": child_usage.ru_maxrss * to_bytes,
        "samples": rows,
    }
    write_json(output, result)
    print(f"Completed {model}: {result['elapsed_seconds']:.1f}s", flush=True)


def summarize(model_result):
    samples = model_result["samples"]
    total = sum(item["evaluation"]["total"] for item in samples)
    matched = sum(item["evaluation"]["matched"] for item in samples)
    by_category = defaultdict(lambda: {"images": 0, "matched": 0, "total": 0, "valid": 0})
    for item in samples:
        bucket = by_category[item["category"]]
        bucket["images"] += 1
        bucket["matched"] += item["evaluation"]["matched"]
        bucket["total"] += item["evaluation"]["total"]
        bucket["valid"] += int(item["evaluation"]["valid"])
    coverages = [item["evaluation"]["coverage"] for item in samples]
    sorted_times = sorted(item["elapsed_seconds"] for item in samples)
    return {
        "model": model_result["model"],
        "label": model_result["label"],
        "images_valid": sum(item["evaluation"]["valid"] for item in samples),
        "images_total": len(samples),
        "matched_tokens": matched,
        "expected_tokens": total,
        "micro_coverage": matched / total if total else 0,
        "mean_image_coverage": sum(coverages) / len(coverages) if coverages else 0,
        "batch_elapsed_seconds": model_result["elapsed_seconds"],
        "initialization_seconds": model_result["initialization_seconds"],
        "median_image_seconds": sorted_times[len(sorted_times) // 2] if sorted_times else None,
        "python_peak_resident_bytes": model_result["python_peak_resident_bytes"],
        "ocr_child_peak_resident_bytes": model_result["ocr_child_peak_resident_bytes"],
        "categories": dict(by_category),
    }


def report(directory):
    manifest = verify(directory)
    summaries = []
    for model in manifest["models"]:
        path = directory / "results" / f"{model}.json"
        if not path.is_file():
            raise ValueError(f"Missing model results: {model}")
        data = read(path)
        if len(data["samples"]) != len(manifest["samples"]):
            raise ValueError(f"Incomplete model results: {model}")
        summaries.append(summarize(data))
    write_json(directory / "report.json", {"models": summaries})
    lines = [
        "# Raw OCR model comparison — held-out sample",
        "",
        f"{len(manifest['samples'])} unique content groups, one unfiltered image and one direct OCR call per image. No VIPI transformations, tiling, filters or cross-view assembly were used.",
        "",
        "| Model | Token coverage | Mean image coverage | Fully matched | Batch | Median/image | Peak RSS |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for item in summaries:
        lines.append(
            f"| {item['label']} | {item['matched_tokens']}/{item['expected_tokens']} ({item['micro_coverage']:.1%}) | "
            f"{item['mean_image_coverage']:.1%} | {item['images_valid']}/{item['images_total']} | "
            f"{item['batch_elapsed_seconds']:.1f}s | {item['median_image_seconds']:.2f}s | "
            f"{item['python_peak_resident_bytes'] / 1024**2:.0f} MiB |"
        )
    lines += ["", "## Per source", "", "| Source | Model | Images | Token coverage | Fully matched |", "|---|---|---:|---:|---:|"]
    for summary in summaries:
        for category, value in summary["categories"].items():
            lines.append(
                f"| {category} | {summary['label']} | {value['images']} | "
                f"{value['matched']}/{value['total']} ({value['matched'] / value['total']:.1%}) | "
                f"{value['valid']}/{value['images']} |"
            )
    lines += [
        "",
        "References are source-provided Silver labels. Target-only references are scored only against their declared target. TextOCR is matched by annotated word regions because its global reading order is not guaranteed. Anamorpher is excluded because its reference applies only after a declared downscale.",
        "",
        "Resource totals and per-image outputs are stored in `report.json` and `results/`. Each selected content group appears once; derived filter variants and Anamorpher are excluded.",
    ]
    (directory / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


def run(directory):
    manifest = verify(directory)
    if (directory / "run_status.json").exists():
        raise ValueError("This experiment was already started; inspect its status first.")
    write_json(
        directory / "run_status.json",
        {
            "state": "running",
            "started_utc": datetime.now(timezone.utc).isoformat(),
            "models": manifest["models"],
            "reference_audit_sha256": sha256(directory / "reference_audit.json"),
        },
    )
    try:
        for model in manifest["models"]:
            print(f"Starting {MODEL_LABELS[model]}", flush=True)
            started = time.perf_counter()
            child = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "research.experiments.ocr.ocr_raw_model_comparison",
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
            result_path = directory / "results" / f"{model}.json"
            model_result = read(result_path)
            model_result["controller_elapsed_seconds"] = time.perf_counter() - started
            model_result["controller_user_cpu_seconds"] = usage.ru_utime
            model_result["controller_system_cpu_seconds"] = usage.ru_stime
            write_json(result_path, model_result)
        report(directory)
    except Exception as error:
        write_json(
            directory / "run_status.json",
            {
                "state": "failed",
                "error": str(error),
                "failed_utc": datetime.now(timezone.utc).isoformat(),
            },
        )
        raise
    write_json(
        directory / "run_status.json",
        {
            "state": "completed",
            "completed_utc": datetime.now(timezone.utc).isoformat(),
            "models": manifest["models"],
            "reference_audit_sha256": sha256(directory / "reference_audit.json"),
        },
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "run", "report", "_model"))
    parser.add_argument("directory", nargs="?", type=Path, default=DEFAULT_RUN)
    parser.add_argument("model", nargs="?", choices=MODEL_ORDER)
    parser.add_argument("--count-per-source", type=int, default=10)
    parser.add_argument("--seed", type=int, default=SEED)
    args = parser.parse_args(argv)
    directory = args.directory.resolve()
    if args.command == "prepare":
        prepare(directory, args.count_per_source, args.seed)
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
