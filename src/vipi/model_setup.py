"""Prepare release-pinned OCR and optional local detector models."""

from .config import (
    DEFAULT_DETECTOR,
    DEFAULT_OCR_MODE,
    CLOUD_OCR_MODELS,
    PROMPT_GUARD_REVISION,
    cache_directory,
    resolve_ocr_model,
    ScanOptions,
)


def setup(
    detector=DEFAULT_DETECTOR,
    *,
    ocr_mode=None,
    ocr_model=None,
    ocr_execution_mode=None,
    ocr_provider=None,
    decision_provider=None,
    progress=None,
):
    from .ocr.models import MODEL_NAMES, prepare_models

    notify = progress or print
    root = cache_directory()
    options = ScanOptions(
        detector=detector,
        ocr_mode=ocr_mode or DEFAULT_OCR_MODE,
        ocr_model=ocr_model,
        ocr_execution_mode=ocr_execution_mode,
        ocr_provider=ocr_provider,
        decision_provider=decision_provider,
    )
    detector = options.resolved_detector
    selected_model = resolve_ocr_model(
        ocr_mode or DEFAULT_OCR_MODE,
        ocr_model,
        execution_mode=ocr_execution_mode,
        provider=ocr_provider,
    )
    model = None
    if (
        ocr_mode is not None
        or ocr_model is not None
        or ocr_execution_mode == "cloud"
        or ocr_provider is not None
    ):
        model = selected_model
        if model in CLOUD_OCR_MODELS:
            notify(
                f"{MODEL_NAMES[model]} uses its hosted API; no local OCR model is downloaded. Credentials are checked at scan time."
            )
        else:
            notify(f"Preparing {MODEL_NAMES[model]}")
    else:
        notify("Preparing PP-OCRv6 models for all modes")
    if model not in CLOUD_OCR_MODELS:
        prepare_models(root / "ocr", model, on_progress=notify)
    if detector == "prompt-guard":
        from .detection.providers.prompt_guard import prepare_model

        notify("Preparing Prompt Guard 2 86M")
        prepare_model(root / "prompt-guard", revision=PROMPT_GUARD_REVISION)
    local_models = {
        name
        for name in (options.resolved_decision_provider, detector)
        if name in {"clef", "d1"}
    }
    for name in sorted(local_models):
        from .local_decisions import prepare_model

        notify(f"Preparing local decision model {name}")
        prepare_model(name, root / "decisions" / name)
    return root
