"""Prepare release-pinned OCR and optional local detector models."""

from .config import (
    DEFAULT_DETECTOR,
    DEFAULT_OCR_MODE,
    PROMPT_GUARD_REVISION,
    cache_directory,
    resolve_ocr_model,
)


def setup(
    detector=DEFAULT_DETECTOR,
    *,
    ocr_mode=None,
    ocr_model=None,
    progress=None,
):
    from .ocr.models import MODEL_NAMES, prepare_models

    notify = progress or print
    root = cache_directory()
    model = None
    if ocr_mode is not None or ocr_model is not None:
        model = resolve_ocr_model(ocr_mode or DEFAULT_OCR_MODE, ocr_model)
        notify(f"Preparing {MODEL_NAMES[model]}")
    else:
        notify("Preparing PP-OCRv6 models for all modes")
    prepare_models(root / "ocr", model, on_progress=notify)
    if detector == "prompt-guard":
        from .detection.providers.prompt_guard import prepare_model

        notify("Preparing Prompt Guard 2 86M")
        prepare_model(root / "prompt-guard", revision=PROMPT_GUARD_REVISION)
    return root
