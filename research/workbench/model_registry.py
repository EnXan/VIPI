"""Active research OCR models and the local interpreter used by each backend."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from vipi.config import (
    WORKBENCH_OCR_MODELS,
    CLOUD_OCR_MODELS,
    OCR_API_KEY_NAMES,
    api_key,
)
from vipi.ocr.models import (
    DEFAULT_MODEL as DEFAULT_MODEL,
    FILES,
    PUBLIC_MODEL_NAMES,
    REQUIRED,
)

ROOT = Path(__file__).resolve().parents[2]
LIGHTON_MODELS = ("lightonocr-3-0.8b", "lightonocr-3-1b", "lightonocr-3-4b")
MODEL_NAMES = {
    **PUBLIC_MODEL_NAMES,
    **{
        name: "LightOnOCR-3 · " + name.removeprefix("lightonocr-3-").upper()
        for name in LIGHTON_MODELS
    },
}
HEAVY_MODELS = (*WORKBENCH_OCR_MODELS, *LIGHTON_MODELS)
SINGLE_PASS_MODELS = (*HEAVY_MODELS, *CLOUD_OCR_MODELS)


def interpreter_for(model):
    vlm = model in HEAVY_MODELS
    setting = "VIPI_OCR_VLM_PYTHON" if vlm else "VIPI_OCR_PYTHON"
    if os.environ.get(setting):
        return str(Path(os.environ[setting]).expanduser().resolve())
    environment = ".venv-ocr-vlm" if vlm else ".venv-ocr"
    executable = (
        ROOT
        / environment
        / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    )
    return str(executable) if executable.is_file() else sys.executable


def backend_for(model, requested):
    return requested if model.startswith("ppocr-v6") else "cpu"


def _packages(interpreter):
    names = (
        "rapidocr",
        "onnxruntime",
        "paddleocr",
        "paddle",
        "docling",
        "torch",
        "transformers",
    )
    code = (
        "import json,importlib.util; print(json.dumps({n:importlib.util.find_spec(n) is not None for n in "
        + repr(names)
        + "}))"
    )
    try:
        answer = subprocess.run(
            [interpreter, "-c", code], capture_output=True, text=True, check=True
        )
        return json.loads(answer.stdout)
    except (OSError, subprocess.SubprocessError, ValueError):
        return {}


def readiness_path(directory):
    return Path(directory) / "workbench-readiness.json"


def model_options(directory, *, include_readiness=True):
    directory = Path(directory)
    interpreters = {interpreter_for(model) for model in MODEL_NAMES}
    packages = {interpreter: _packages(interpreter) for interpreter in interpreters}
    ready = {}
    if include_readiness and readiness_path(directory).is_file():
        ready = json.loads(readiness_path(directory).read_text()).get("models", {})
    options = []
    for model, label in MODEL_NAMES.items():
        runtime = packages[interpreter_for(model)]
        reason = None
        if model in CLOUD_OCR_MODELS:
            names = OCR_API_KEY_NAMES[model]
            if not api_key(*names):
                reason = f"Set {names[0]} to use this OCR API."
        elif model in LIGHTON_MODELS:
            if not runtime.get("transformers") or not runtime.get("torch"):
                reason = "Install Transformers and PyTorch in the VLM runtime."
            elif not (directory / "candidates" / model / "config.json").is_file():
                reason = "Prepare the LightOn model weights in models/ocr/candidates."
        elif model in WORKBENCH_OCR_MODELS:
            required = (
                ("paddleocr", "paddle") if model == "paddleocr-vl-1.6" else ("docling",)
            )
            if not all(runtime.get(name) for name in required):
                reason = "Install the optional document model runtime; see research/workbench/README.md."
            elif not (directory / model / "READY").is_file():
                reason = f"Prepare the model: python -m research.workbench prepare-models --model {model}"
        else:
            if model == "tesseract":
                if not shutil.which("tesseract"):
                    reason = "Install Tesseract 5."
            elif not runtime.get("rapidocr") or not runtime.get("onnxruntime"):
                reason = "Install the ocr extra in the standard OCR runtime."
            if reason is None and any(
                not (directory / FILES[key]["file"]).is_file()
                for key in REQUIRED[model]
            ):
                reason = f"Prepare the weights: python -m research.workbench prepare-models --model {model}"
        check = ready.get(model) or {}
        if reason is None and check.get("state") == "failed":
            reason = "Round 0 failed: " + check.get("error", "inspect its saved report")
        options.append(
            {
                "id": model,
                "label": label,
                "available": reason is None,
                "reason": reason,
                "round0": check.get("state", "untested"),
                "runtime": interpreter_for(model),
            }
        )
    return options


def validate_models(models, directory, *, include_readiness=True):
    if (
        not isinstance(models, list)
        or not models
        or not all(isinstance(model, str) for model in models)
    ):
        raise ValueError("Choose at least one OCR model.")
    if len(set(models)) != len(models):
        raise ValueError("Choose each OCR model once.")
    available = {
        item["id"]: item
        for item in model_options(directory, include_readiness=include_readiness)
    }
    for model in models:
        if model not in available:
            raise ValueError(f"Unsupported research OCR model: {model}")
        if not available[model]["available"]:
            raise ValueError(
                f"{available[model]['label']}: {available[model]['reason']}"
            )
    return models


def validate_model(model, directory):
    validate_models([model], directory)


def create_direct_engine(
    model, directory, *, profile="baseline", backend="cpu", threads=1
):
    if model in LIGHTON_MODELS:
        from .lighton import LightOnEngine

        return LightOnEngine(model, directory)
    if model in WORKBENCH_OCR_MODELS:
        from .ocr_models import create_engine

        return create_engine(model, directory)
    from vipi.ocr.engines import create_engine

    return create_engine(
        model,
        directory,
        backend=backend,
        threads=threads,
        native_pipeline=profile == "baseline",
    )


def create_engine(model, directory, *, profile="baseline", backend="cpu", threads=1):
    from importlib.util import find_spec

    external = model in HEAVY_MODELS or (
        model.startswith("ppocr-v6") and find_spec("onnxruntime") is None
    )
    if external:
        from .model_runtime import WorkerEngine

        return WorkerEngine(
            model, directory, profile=profile, backend=backend, threads=threads
        )
    return create_direct_engine(
        model, directory, profile=profile, backend=backend, threads=threads
    )
