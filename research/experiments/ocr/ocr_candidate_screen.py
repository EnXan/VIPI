"""Screen raw OCR candidates on a small, source-stratified image sample."""

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import importlib
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from PIL import Image

from research.experiments.ocr import ocr_raw_model_comparison as raw
from research.evaluation.metrics import score, tokens
from vipi.ocr.models import FILES, REQUIRED, sha256
from vipi.storage.ocr import write_json

ROOT = Path(__file__).resolve().parents[3]
MODEL_DIR = ROOT / "models/ocr/candidates"
OLD_AUDIT_RUN = ROOT / "runs/ocr-model-comparison/2026-10-20-raw-holdout-02"
SEED = 20261020

MODEL_LABELS = {
    "ppocr-v6-medium": "PP-OCRv6 · medium",
    "ppocr-v6-small": "PP-OCRv6 · small",
    "ppocr-v6-tiny": "PP-OCRv6 · tiny",
    "surya-ocr-2": "Surya OCR 2 · 0.69B",
    "lightonocr-3-0.8b": "LightOnOCR-3 · 0.8B",
    "lightonocr-3-1b": "LightOnOCR-3 · 1B",
    "lightonocr-3-4b": "LightOnOCR-3 · 4B",
    "florence-2-base-ft": "Florence-2 · base-ft",
    "florence-2-large-ft": "Florence-2 · large-ft",
}
MODEL_REPOSITORIES = {
    "surya-ocr-2": "datalab-to/surya-ocr-2",
    "lightonocr-3-0.8b": "lightonai/LightOnOCR-3-0.8B",
    "lightonocr-3-1b": "lightonai/LightOnOCR-3-1B",
    "lightonocr-3-4b": "lightonai/LightOnOCR-3-4B",
    "florence-2-base-ft": "microsoft/Florence-2-base-ft",
    "florence-2-large-ft": "microsoft/Florence-2-large-ft",
}
MODEL_ORDER = tuple(MODEL_LABELS)
TINY_MODEL_DIR = MODEL_DIR / "ppocr-v6-tiny"
TINY_MODEL_FILES = {
    "PP-OCRv6_det_tiny.onnx": "f42c0fbd294d95eac1a550e131b277dac97462c8025fa4b6c3cec1b7894bd3d5",
    "PP-OCRv6_rec_tiny.onnx": "e16e242de5937ad92609223f19bc2aff3727ee40b095f996907c24749bad251b",
}
BASE_COMPARE = raw.compare
LIGHTON_MAX_NEW_TOKENS = 512
FLORENCE_MAX_NEW_TOKENS = 512
BASE_CODE_HASHES = raw.code_hashes
BASE_LIBRARY_VERSIONS = raw.library_versions
BASE_MAKE_ENGINE = raw.make_engine


def candidate_code_hashes():
    hashes = BASE_CODE_HASHES()
    filename = "research/experiments/ocr/ocr_candidate_screen.py"
    hashes[filename] = sha256(ROOT / filename)
    return hashes


def model_directory(model):
    return MODEL_DIR / model


def tiny_model_files():
    paths = {name: TINY_MODEL_DIR / name for name in TINY_MODEL_FILES}
    cls_name = FILES["ch_PP-LCNet_x0_25_textline_ori_cls_mobile"]["file"]
    paths[cls_name] = ROOT / "models/ocr" / cls_name
    for name, expected_hash in TINY_MODEL_FILES.items():
        path = paths[name]
        if not path.is_file() or sha256(path) != expected_hash:
            raise ValueError(f"Missing or invalid PP-OCRv6 tiny model file: {path}")
    return paths


def model_revisions(models):
    revisions = {}
    remote_models = [model for model in models if model in MODEL_REPOSITORIES]
    if not remote_models:
        return revisions

    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
    from huggingface_hub import HfApi, snapshot_download

    api = HfApi()
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    for model in remote_models:
        repository = MODEL_REPOSITORIES[model]
        revision = api.model_info(repository).sha
        snapshot_download(
            repository,
            revision=revision,
            local_dir=model_directory(model),
            max_workers=2,
        )
        revisions[model] = {"repository": repository, "revision": revision}
    return revisions


def candidate_model_file_hashes():
    result = {}
    selected = raw.MODEL_ORDER
    for model in selected:
        if model == "ppocr-v6-medium":
            for key in REQUIRED["ppocr-v6"]:
                info = FILES[key]
                path = ROOT / "models/ocr" / info["file"]
                if not path.is_file() or sha256(path) != info["sha256"]:
                    raise ValueError(f"Missing or invalid PP-OCRv6 model file: {path}")
                result[f"{model}/{info['file']}"] = sha256(path)
        elif model == "ppocr-v6-small":
            for name, path in raw.small_model_files().items():
                result[f"{model}/{name}"] = sha256(path)
        elif model == "ppocr-v6-tiny":
            for name, path in tiny_model_files().items():
                result[f"{model}/{name}"] = sha256(path)
        elif model in MODEL_REPOSITORIES:
            directory = model_directory(model)
            files = [
                path
                for path in directory.rglob("*")
                if path.is_file() and ".cache" not in path.parts
            ]
            if not files:
                raise ValueError(f"Model files are missing for {model}.")
            for path in sorted(files):
                result[f"{model}/{path.relative_to(directory).as_posix()}"] = sha256(
                    path
                )
        else:
            raise ValueError(f"Unknown candidate model: {model}")
    return result


def candidate_library_versions():
    versions = BASE_LIBRARY_VERSIONS()
    versions.update(
        {
            name: importlib.metadata.version(name)
            for name in (
                "torch",
                "torchvision",
                "transformers",
                "huggingface-hub",
                "timm",
                "einops",
            )
        }
    )
    return versions


def protocol_hash(manifest):
    keys = (
        "seed",
        "count_per_source",
        "models",
        "model_files_sha256",
        "model_revisions",
        "backend",
        "threads",
        "code_hashes",
        "samples",
        "design",
    )
    return hashlib.sha256(
        json.dumps({key: manifest[key] for key in keys}, sort_keys=True).encode()
    ).hexdigest()


def bind_raw_comparison(models):
    raw.MODEL_ORDER = tuple(models)
    raw.MODEL_LABELS = MODEL_LABELS
    raw.model_file_hashes = candidate_model_file_hashes
    raw.code_hashes = candidate_code_hashes
    raw.library_versions = candidate_library_versions
    raw.protocol_hash = protocol_hash
    raw.make_engine = make_engine
    raw.compare = candidate_compare


def candidate_compare(reference, text, regions):
    if reference["reading_order_known"] or regions:
        return BASE_COMPARE(reference, text, regions)

    expected = [
        token
        for region in reference.get("regions", [])
        for token in tokens(region["text"])
    ]
    if not expected:
        expected = tokens(reference.get("text", ""))
    remaining = Counter(tokens(text))
    matched = set()
    for index, token in enumerate(expected):
        if remaining[token]:
            matched.add(index)
            remaining[token] -= 1
    result = score(expected, matched)
    result["comparison_mode"] = "unordered_token_multiset"
    return result, expected, matched


def copy_reviewed_audit(directory):
    previous_manifest = OLD_AUDIT_RUN / "manifest.json"
    previous_audit = OLD_AUDIT_RUN / "reference_audit.json"
    if not previous_manifest.is_file() or not previous_audit.is_file():
        return 0
    old_manifest = raw.read(previous_manifest)
    new_manifest = raw.read(directory / "manifest.json")
    old_samples = {sample["id"]: sample for sample in old_manifest["samples"]}
    new_samples = {sample["id"]: sample for sample in new_manifest["samples"]}
    matching_ids = set(old_samples) & set(new_samples)
    if any(
        new_samples[sample_id] != old_samples[sample_id] for sample_id in matching_ids
    ):
        return 0
    audit = raw.read(previous_audit)
    if set(audit) != set(old_samples) or any(
        item.get("status") != "reviewed" for item in audit.values()
    ):
        return 0
    new_audit = raw.read(directory / "reference_audit.json")
    for sample_id in matching_ids:
        new_audit[sample_id] = audit[sample_id]
    write_json(directory / "reference_audit.json", new_audit)
    return len(matching_ids)


class LightOnEngine:
    """Grounding adapter for LightOnOCR-3 and Surya OCR 2."""

    def __init__(self, model):
        import torch
        from transformers import AutoProcessor

        model_path = model_directory(model)
        if model == "lightonocr-3-1b":
            from transformers import (
                LightOnOcrForConditionalGeneration,
                LightOnOcrProcessor,
            )

            processor_type = LightOnOcrProcessor
            model_type = LightOnOcrForConditionalGeneration
        else:
            model_type = getattr(
                importlib.import_module("transformers"), "AutoModelForMultimodalLM"
            )
            processor_type = AutoProcessor
        torch.set_num_threads(max(1, os.cpu_count() or 1))
        try:
            torch.set_num_interop_threads(1)
        except RuntimeError:
            pass
        self.torch = torch
        self.model_name = model
        self.processor = processor_type.from_pretrained(
            model_path, local_files_only=True
        )
        self.model = (
            model_type.from_pretrained(
                model_path,
                torch_dtype=torch.bfloat16,
                local_files_only=True,
            )
            .to("cpu")
            .eval()
        )

    def recognize(self, image: Image.Image):
        content = [{"type": "image", "url": image.convert("RGB")}]
        inputs = self.processor.apply_chat_template(
            [{"role": "user", "content": content}],
            add_generation_prompt=True,
            tokenize=True,
            return_dict=True,
            return_tensors="pt",
            enable_thinking=False,
        )
        self.torch.manual_seed(42)
        with self.torch.inference_mode():
            output = self.model.generate(
                **inputs,
                max_new_tokens=LIGHTON_MAX_NEW_TOKENS,
                do_sample=False,
            )
        if getattr(self.model.config, "is_encoder_decoder", False):
            generated = output[0]
        else:
            generated = output[0, inputs["input_ids"].shape[-1] :]
        text = self.processor.decode(generated, skip_special_tokens=True)
        if self.model_name == "surya-ocr-2":
            return {"text": text.strip(), "regions": []}
        return parse_lighton_grounding(text, image.size)


class FlorenceEngine:
    """Florence-2 OCR-with-region adapter."""

    def __init__(self, model):
        import torch
        from transformers import AutoModelForCausalLM, AutoProcessor

        model_path = model_directory(model)
        self.processor = AutoProcessor.from_pretrained(
            model_path, local_files_only=True, trust_remote_code=True
        )
        self.model = (
            AutoModelForCausalLM.from_pretrained(
                model_path,
                torch_dtype=torch.float32,
                local_files_only=True,
                trust_remote_code=True,
            )
            .to("cpu")
            .eval()
        )
        self.torch = torch

    def recognize(self, image):
        task = "<OCR_WITH_REGION>"
        inputs = self.processor(
            text=task, images=image.convert("RGB"), return_tensors="pt"
        )
        with self.torch.inference_mode():
            output = self.model.generate(
                input_ids=inputs["input_ids"],
                pixel_values=inputs["pixel_values"],
                max_new_tokens=FLORENCE_MAX_NEW_TOKENS,
                do_sample=False,
                num_beams=1,
            )
        decoded = self.processor.batch_decode(output, skip_special_tokens=False)[0]
        parsed = self.processor.post_process_generation(
            decoded, task=task, image_size=image.size
        )
        payload = parsed.get(task, parsed)
        labels = payload.get("labels", [])
        boxes = payload.get("quad_boxes", [])
        regions = []
        for label, box in zip(labels, boxes):
            points = list(zip(box[::2], box[1::2]))
            regions.append({"text": label, "polygon": [[x, y] for x, y in points]})
        return {"text": "\n".join(labels), "regions": regions}


def parse_lighton_grounding(text, size):
    """Parse LightOnOCR grounding blocks, whose coordinates are normalized to 1000."""
    import re

    marker = re.compile(
        r"!\[(?P<label>[^\]]+)\]\(\s*(?P<x1>\d+(?:\.\d+)?)\s*,\s*"
        r"(?P<y1>\d+(?:\.\d+)?)\s*,\s*(?P<x2>\d+(?:\.\d+)?)\s*,\s*"
        r"(?P<y2>\d+(?:\.\d+)?)\s*\)"
    )
    matches = list(marker.finditer(text))
    regions = []
    for index, match in enumerate(matches):
        x1, y1, x2, y2 = (float(match.group(name)) for name in ("x1", "y1", "x2", "y2"))
        x1, x2 = x1 * size[0] / 1000, x2 * size[0] / 1000
        y1, y2 = y1 * size[1] / 1000, y2 * size[1] / 1000
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        block = text[match.end() : end].strip()
        if not block:
            continue
        polygon = [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]
        regions.append(
            {"text": block, "polygon": polygon, "label": match.group("label")}
        )
    cleaned = "\n".join(region["text"] for region in regions)
    if not regions:
        cleaned = text.strip()
    return {"text": cleaned, "regions": regions}


def make_engine(model, directory, threads):
    if model == "ppocr-v6-tiny":
        return raw.V6SmallEngine(
            directory,
            threads,
            size="tiny",
            model_paths=tiny_model_files(),
        )
    if model == "surya-ocr-2":
        raise RuntimeError(
            "Surya OCR 2 needs its documented surya-ocr inference runtime; "
            "the generic Transformers path does not return OCR results."
        )
    if model in MODEL_REPOSITORIES and not model.startswith("florence-2-"):
        return LightOnEngine(model)
    if model.startswith("florence-2-"):
        return FlorenceEngine(model)
    return BASE_MAKE_ENGINE(model, directory, threads)


def prepare(directory, models, count_per_source, seed):
    if directory.exists():
        raise ValueError(
            "Choose a new experiment directory; completed runs are immutable."
        )
    unknown = sorted(set(models) - set(MODEL_ORDER))
    if unknown:
        raise ValueError("Unknown candidate models: " + ", ".join(unknown))
    revisions = model_revisions(models)
    bind_raw_comparison(models)
    raw.prepare(directory, count_per_source, seed)
    manifest = raw.read(directory / "manifest.json")
    manifest["model_revisions"] = revisions
    manifest["protocol_sha256"] = protocol_hash(manifest)
    write_json(directory / "manifest.json", manifest)
    reused_audit = copy_reviewed_audit(directory)
    print("Tesseract is not included in this candidate screen.")
    if reused_audit:
        print(f"Reused reviewed references for {reused_audit} matching samples.")


def run(directory, models):
    bind_raw_comparison(models)
    manifest = raw.verify(directory)
    if (directory / "run_status.json").exists():
        raise ValueError(
            "This experiment was already started; inspect its status first."
        )
    write_json(
        directory / "run_status.json",
        {
            "state": "running",
            "started_utc": datetime.now(timezone.utc).isoformat(),
            "models": manifest["models"],
            "reference_audit_sha256": sha256(directory / "reference_audit.json"),
            "model_status": {
                model: {"state": "pending"} for model in manifest["models"]
            },
        },
    )
    status_path = directory / "run_status.json"
    status = raw.read(status_path)
    for model in manifest["models"]:
        print(f"Starting {MODEL_LABELS[model]}", flush=True)
        started = time.perf_counter()
        try:
            child = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "research.experiments.ocr.ocr_candidate_screen",
                    "_model",
                    str(directory),
                    model,
                ],
                cwd=ROOT,
                env={
                    **os.environ,
                    "HF_HOME": str(directory / "cache" / "huggingface"),
                    "HF_MODULES_CACHE": str(
                        directory / "cache" / "huggingface-modules"
                    ),
                },
            )
            _, wait_status, usage = os.wait4(child.pid, 0)
            child.returncode = os.waitstatus_to_exitcode(wait_status)
            if child.returncode:
                raise RuntimeError(f"comparison process exited with {child.returncode}")
            result_path = directory / "results" / f"{model}.json"
            model_result = raw.read(result_path)
            model_result["controller_elapsed_seconds"] = time.perf_counter() - started
            model_result["controller_user_cpu_seconds"] = usage.ru_utime
            model_result["controller_system_cpu_seconds"] = usage.ru_stime
            write_json(result_path, model_result)
            status["model_status"][model] = {
                "state": "completed",
                "elapsed_seconds": time.perf_counter() - started,
            }
        except Exception as error:
            status["model_status"][model] = {
                "state": "failed",
                "error": str(error),
                "elapsed_seconds": time.perf_counter() - started,
            }
            print(f"Failed {MODEL_LABELS[model]}: {error}", flush=True)
        write_json(status_path, status)
    report(directory)
    failed = [
        model
        for model, result in status["model_status"].items()
        if result["state"] == "failed"
    ]
    write_json(
        directory / "run_status.json",
        {
            "state": "completed_with_failures" if failed else "completed",
            "completed_utc": datetime.now(timezone.utc).isoformat(),
            "models": manifest["models"],
            "reference_audit_sha256": sha256(directory / "reference_audit.json"),
            "model_status": status["model_status"],
        },
    )


def report(directory):
    manifest = raw.verify(directory)
    status_path = directory / "run_status.json"
    status = raw.read(status_path) if status_path.is_file() else {"model_status": {}}
    summaries = []
    failures = []
    for model in manifest["models"]:
        path = directory / "results" / f"{model}.json"
        if not path.is_file():
            failures.append(
                {
                    "model": model,
                    "label": MODEL_LABELS[model],
                    "error": status.get("model_status", {})
                    .get(model, {})
                    .get("error", "No complete result was saved."),
                }
            )
            continue
        result = raw.read(path)
        if len(result["samples"]) != len(manifest["samples"]):
            failures.append(
                {
                    "model": model,
                    "label": MODEL_LABELS[model],
                    "error": "Inference stopped before every sample completed.",
                }
            )
            continue
        summaries.append(raw.summarize(result))
    write_json(directory / "report.json", {"models": summaries, "failures": failures})
    lines = [
        "# Raw OCR candidate screen — held-out sample",
        "",
        f"{len(manifest['samples'])} unique content groups; one raw image and one direct OCR call per image. No VIPI transformations, tiling or cross-view assembly were used.",
        "",
        "| Model | Token coverage | Fully matched | Batch | Median/image | Peak RSS |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for item in summaries:
        lines.append(
            f"| {item['label']} | {item['matched_tokens']}/{item['expected_tokens']} ({item['micro_coverage']:.1%}) | "
            f"{item['images_valid']}/{item['images_total']} | {item['batch_elapsed_seconds']:.1f}s | "
            f"{item['median_image_seconds']:.2f}s | {item['python_peak_resident_bytes'] / 1024**2:.0f} MiB |"
        )
    if failures:
        lines.extend(["", "## Candidates that did not complete", ""])
        for item in failures:
            lines.append(f"- **{item['label']}**: {item['error']}")
    lines.extend(
        [
            "",
            "## Per source",
            "",
            "| Source | Model | Images | Token coverage | Fully matched |",
            "|---|---|---:|---:|---:|",
        ]
    )
    for summary in summaries:
        for category, value in summary["categories"].items():
            coverage = value["matched"] / value["total"] if value["total"] else 0
            lines.append(
                f"| {category} | {summary['label']} | {value['images']} | "
                f"{value['matched']}/{value['total']} ({coverage:.1%}) | "
                f"{value['valid']}/{value['images']} |"
            )
    lines.extend(
        [
            "",
            "References are source-provided Silver labels. Target-only references stay target-only; TextOCR is matched by word regions when the model provides coordinates. Anamorpher is excluded because its reference applies only after its declared downscale.",
            "",
            "Resource totals, per-image outputs and failure details are saved in `report.json` and `results/`.",
        ]
    )
    (directory / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare_parser = commands.add_parser(
        "prepare", help="Freeze a sample and model set"
    )
    prepare_parser.add_argument("directory", type=Path)
    prepare_parser.add_argument(
        "--models", nargs="+", choices=MODEL_ORDER, default=MODEL_ORDER
    )
    prepare_parser.add_argument("--count-per-source", type=int, default=2)
    prepare_parser.add_argument("--seed", type=int, default=SEED)
    for name in ("run", "report"):
        command = commands.add_parser(name)
        command.add_argument("directory", type=Path)
    model_parser = commands.add_parser("_model")
    model_parser.add_argument("directory", type=Path)
    model_parser.add_argument("model", choices=MODEL_ORDER)
    args = parser.parse_args(argv)
    directory = args.directory.resolve()
    if args.command == "prepare":
        prepare(directory, args.models, args.count_per_source, args.seed)
    else:
        manifest = raw.read(directory / "manifest.json")
        bind_raw_comparison(manifest["models"])
        if args.command == "run":
            run(directory, manifest["models"])
        elif args.command == "report":
            raw.report(directory)
        else:
            raw.run_model(directory, args.model)


if __name__ == "__main__":
    main()
