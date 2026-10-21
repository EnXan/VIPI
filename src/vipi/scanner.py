"""Shared image scanning; CLI/file selection and report formatting stay adapters."""

from contextlib import ExitStack
import time

from .config import (
    DEFAULT_DETECTOR,
    DEFAULT_OCR_MODE,
    DEFAULT_THRESHOLD,
    ScanOptions,
    cache_directory,
)
from .inputs import select_images
from .reporting import file_record, finish, report_overwrites_input
from .results import ScanResult


def scan_image(image, *, options=None, session=None, provider=None, on_event=None):
    """Scan an image path or bytes and return typed OCR and detection results.

    A caller can reuse a session/provider across images. No existing run directory,
    Flask application or dataset catalog is required.
    """
    from .detection.pipeline import detect_ocr
    from .detection.providers import prepare_provider
    from .ocr.session import OcrSession

    options = options or ScanOptions()
    provider = provider or prepare_provider(
        options.detector, cache_directory() / "prompt-guard"
    )
    with ExitStack() as resources:
        if session is None:
            session = resources.enter_context(
                OcrSession(
                    mode=options.ocr_mode,
                    model=options.resolved_ocr_model,
                )
            )
        ocr = session.extract(image, on_event)
        detection = detect_ocr(
            ocr,
            options=options.detection_options(),
            provider_factory=lambda name: provider,
            on_event=on_event,
        )
    return ScanResult(ocr, detection, provider.model, provider.identity)


def scan(
    paths,
    *,
    detector=DEFAULT_DETECTOR,
    threshold=DEFAULT_THRESHOLD,
    ocr_mode=DEFAULT_OCR_MODE,
    ocr_model=None,
    diff=None,
    output=None,
    progress=None,
    on_result=None,
):
    """Scan selected inputs sequentially and produce the public report schema."""
    started = time.perf_counter()
    root = cache_directory()
    report = {
        "schema_version": 1,
        "detector": detector,
        "threshold": threshold,
        "evidence_scope": "final_ocr",
        "diff": None,
        "ocr": None,
        "files": [],
        "skipped": [],
        "errors": [],
    }

    def notify(message):
        if progress:
            progress(message)

    try:
        options = ScanOptions(detector, threshold, ocr_mode, ocr_model)
        report["ocr_mode"] = options.ocr_mode
        report["ocr_model"] = options.resolved_ocr_model
        selection = select_images(paths, diff=diff, excluded=[root])
        report.update(
            diff=selection.diff, skipped=selection.skipped, errors=selection.errors
        )
        report["files"] = [
            {"path": str(source.path), "status": "not_scanned"}
            for source in selection.images
        ]
        if report_overwrites_input(
            output, (source.path for source in selection.images)
        ):
            raise ValueError("The output report must not overwrite an input image.")
        if not selection.images:
            notify("No supported images selected.")
            return finish(report, started)

        from .detection.providers import prepare_provider
        from .ocr.session import OcrSession

        provider = prepare_provider(detector, root / "prompt-guard")
        with OcrSession(
            root, mode=options.ocr_mode, model=options.resolved_ocr_model
        ) as session:
            report["ocr"] = session.metadata
            for index, (source, item) in enumerate(
                zip(selection.images, report["files"]), 1
            ):
                notify(
                    f"[{index}/{len(selection.images)}] Scanning {str(source.path)!r}"
                )
                result = None
                try:
                    with source.local_file() as image:
                        result = scan_image(
                            image, options=options, session=session, provider=provider
                        )
                    item.update(file_record(result))
                except KeyboardInterrupt:
                    item.update(status="error", errors=["Scan interrupted."])
                    report["errors"].append(
                        {
                            "error": "Scan interrupted; remaining images were not scanned."
                        }
                    )
                    break
                except Exception as error:
                    item.update(status="error", errors=[str(error)])
                    if getattr(error, "artifacts", None) is not None:
                        item["artifacts"] = str(error.artifacts)
                if result is not None and on_result:
                    on_result(source.path, result)
                score = item.get("signals", {}).get(detector, {}).get("max_score")
                score_text = f", score={score * 100:g}" if score is not None else ""
                notify(
                    f"  {item.get('verdict', 'error')} ({item['status']}{score_text})"
                )
    except (Exception, KeyboardInterrupt) as error:
        message = (
            "Missing runtime dependencies. Install VIPI with the ocr extra "
            "(and detector-local for Prompt Guard)."
            if isinstance(error, ModuleNotFoundError)
            else str(error) or "Scan interrupted."
        )
        report["errors"].append({"error": message})
    return finish(report, started)
