"""Explicit, checksum-verified model preparation. Extraction never downloads."""

import json
import shutil
import urllib.request
from pathlib import Path

from vipi.config import OCR_MODES
from vipi.storage.files import sha256

MODEL_NAMES = {
    "ppocr-v5": "PP-OCRv5 · server / English",
    "ppocr-v6": "PP-OCRv6 · medium",
    "ppocr-v6-medium": "PP-OCRv6 · medium",
    "ppocr-v6-small": "PP-OCRv6 · small",
    "ppocr-v6-tiny": "PP-OCRv6 · tiny",
    "tesseract": "Tesseract · English / best",
}
PUBLIC_MODEL_NAMES = {
    "ppocr-v6": MODEL_NAMES["ppocr-v6"],
    "ppocr-v6-small": MODEL_NAMES["ppocr-v6-small"],
    "ppocr-v6-tiny": MODEL_NAMES["ppocr-v6-tiny"],
    "tesseract": MODEL_NAMES["tesseract"],
}
DEFAULT_MODEL = "ppocr-v6"
FILES = json.loads(Path(__file__).with_name("model_files.json").read_text())
REQUIRED = {
    "ppocr-v5": (
        "ch_PP-OCRv5_det_server",
        "en_PP-OCRv5_rec_mobile",
        "ch_PP-LCNet_x0_25_textline_ori_cls_mobile",
    ),
    "ppocr-v6": (
        "multi_PP-OCRv6_det_medium",
        "multi_PP-OCRv6_rec_medium",
        "ch_PP-LCNet_x0_25_textline_ori_cls_mobile",
    ),
    "ppocr-v6-medium": (
        "multi_PP-OCRv6_det_medium",
        "multi_PP-OCRv6_rec_medium",
        "ch_PP-LCNet_x0_25_textline_ori_cls_mobile",
    ),
    "ppocr-v6-small": (
        "multi_PP-OCRv6_det_small",
        "multi_PP-OCRv6_rec_small",
        "ch_PP-LCNet_x0_25_textline_ori_cls_mobile",
    ),
    "ppocr-v6-tiny": (
        "multi_PP-OCRv6_det_tiny",
        "multi_PP-OCRv6_rec_tiny",
        "ch_PP-LCNet_x0_25_textline_ori_cls_mobile",
    ),
    "tesseract": ("tesseract-eng",),
}


def validate_model(model: str, directory: Path, *, verify=False):
    if model not in MODEL_NAMES:
        raise ValueError(f"Unknown OCR model: {model}")
    if model == "tesseract" and not shutil.which("tesseract"):
        raise ValueError("Tesseract is not installed. Install Tesseract 5 separately.")
    for key in REQUIRED[model]:
        info = FILES[key]
        path = directory / info["file"]
        if not path.is_file():
            raise ValueError(
                f"Model files missing. Run: vipi setup --ocr-model {model}"
            )
        if verify and sha256(path) != info["sha256"]:
            raise ValueError(
                f"Model checksum mismatch: {path.name}. Prepare models again."
            )


def model_options(directory: Path) -> list[dict]:
    options = []
    for key, label in PUBLIC_MODEL_NAMES.items():
        try:
            validate_model(key, directory)
            reason = None
        except ValueError as error:
            reason = str(error)
        options.append(
            {"id": key, "label": label, "available": reason is None, "reason": reason}
        )
    return options


def prepare_models(directory: Path, model: str | None = None, on_progress=print):
    directory.mkdir(parents=True, exist_ok=True)
    selected_models = [model] if model else tuple(dict.fromkeys(OCR_MODES.values()))
    unknown = sorted(set(selected_models) - set(REQUIRED))
    if unknown:
        raise ValueError("Unknown OCR model: " + ", ".join(unknown))
    keys = dict.fromkeys(key for name in selected_models for key in REQUIRED[name])
    for key in keys:
        info = FILES[key]
        target = directory / info["file"]
        if target.is_file() and sha256(target) == info["sha256"]:
            on_progress(f"Ready: {target.name}")
            continue
        on_progress(f"Downloading: {target.name}")
        temporary = target.with_suffix(target.suffix + ".download")
        try:
            request = urllib.request.Request(
                info["url"], headers={"User-Agent": "VIPI-OCR/0.1"}
            )
            with (
                urllib.request.urlopen(request, timeout=60) as response,
                temporary.open("wb") as file,
            ):
                shutil.copyfileobj(response, file)
            if sha256(temporary) != info["sha256"]:
                raise ValueError(f"Downloaded model checksum mismatch: {target.name}")
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
        on_progress(f"Ready: {target.name}")
