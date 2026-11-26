"""Shared image scanning; CLI/file selection and report formatting stay adapters."""

from contextlib import ExitStack
from io import BytesIO
import time

from .config import (
    CLOUD_DECISION_PROVIDERS,
    DEFAULT_DETECTOR,
    DEFAULT_OCR_MODE,
    ScanOptions,
    cache_directory,
)
from .inputs import select_images
from .reporting import file_record, finish, report_overwrites_input
from .results import ScanResult


def scan_image(image, *, options=None, session=None, provider=None, on_event=None):
    """Scan an image path or bytes and return a typed scan result.

    An `.svg` path is rendered for OCR, and its source text is checked as a
    second reading (ADR 0078). For a raster image, the text in its metadata is
    the second reading (ADR 0083). QR and barcode payloads in the scanned
    raster are a further reading (ADR 0084). An image with transparent pixels
    is also scanned on black and with alpha dropped (ADR 0085).

    A caller can reuse a session/provider across images. No existing run directory,
    Flask application or dataset catalog is required.
    """
    from .detection.pipeline import detect_ocr
    from .barcodes import read_codes
    from .detection.providers import prepare_provider
    from .image_metadata import read_metadata
    from .images import decode_image
    from .svg import is_svg, prepare_svg
    from .transparency import read_views

    svg = prepare_svg(image) if is_svg(image) else None
    transparency = (
        None
        if svg
        else read_views(BytesIO(image) if isinstance(image, bytes) else image)
    )
    options = options or ScanOptions()
    provider = provider or prepare_provider(
        options.resolved_detector, cache_directory() / "wolf-defender"
    )
    source = svg.rendered.png if svg else image
    with ExitStack() as resources:
        if session is None:
            from .ocr.session import OcrSession

            session = resources.enter_context(
                OcrSession(
                    mode=options.ocr_mode,
                    model=options.resolved_ocr_model,
                    decision_provider=options.resolved_decision_provider,
                )
            )
        ocr = session.extract(source, on_event)
        if transparency:
            transparency = transparency.scanned(
                ocr, lambda png: session.extract(png, on_event)
            )
        metadata = None if svg else read_metadata(image)
        raster = BytesIO(source) if isinstance(source, bytes) else source
        barcodes = read_codes(decode_image(raster, max_pixels=None))
        if svg and ocr.artifacts is not None:
            (ocr.artifacts / "input.svg").write_bytes(svg.data)
        detection = detect_ocr(
            ocr,
            options=options.detection_options(),
            provider_factory=lambda name: provider,
            on_event=on_event,
            source_text=svg.document.detector_text if svg else None,
            metadata_text=metadata.detector_text if metadata else None,
            barcode_text=barcodes.detector_text,
            views=transparency.ocr_views if transparency else None,
            incomplete=(svg.incomplete if svg else metadata.incomplete)
            + barcodes.incomplete
            + (transparency.incomplete if transparency else ()),
        )
    return ScanResult(
        ocr,
        detection,
        provider.model,
        provider.identity,
        svg,
        metadata,
        barcodes,
        transparency,
    )


def scan(
    paths,
    *,
    detector=DEFAULT_DETECTOR,
    threshold=None,
    ocr_mode=DEFAULT_OCR_MODE,
    ocr_model=None,
    ocr_execution_mode=None,
    ocr_provider=None,
    decision_provider=None,
    diff=None,
    exclude_patterns=(),
    output=None,
    progress=None,
    on_result=None,
    list_only=False,
):
    """Scan selected inputs sequentially and produce the public report schema.

    With `list_only`, stop after input selection: no models, providers or
    credentials are used and every selected file is reported as `selected`.
    """
    started = time.perf_counter()
    root = cache_directory()
    report = {
        "schema_version": 2,
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
        options = ScanOptions(
            detector,
            threshold,
            ocr_mode,
            ocr_model,
            ocr_execution_mode,
            ocr_provider,
            decision_provider,
        )
        detector = options.resolved_detector
        if detector in CLOUD_DECISION_PROVIDERS:
            report["evidence_scope"] = "final_ocr_with_image_check"
        report["detector"] = detector
        report["threshold"] = options.resolved_threshold
        report["decision_provider"] = options.resolved_decision_provider
        report["ocr_mode"] = options.resolved_ocr_mode
        report["ocr_execution_mode"] = options.resolved_ocr_execution_mode
        report["ocr_provider"] = options.resolved_ocr_provider
        report["ocr_model"] = options.resolved_ocr_model
        selection = select_images(
            paths,
            diff=diff,
            excluded=[root],
            exclude_patterns=exclude_patterns,
        )
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
        if list_only:
            report["list_only"] = True
            for item in report["files"]:
                item["status"] = "selected"
            return finish(report, started)
        if not selection.images:
            notify("No supported images selected.")
            return finish(report, started)

        from .detection.providers import prepare_provider

        provider = prepare_provider(detector, root / "wolf-defender")
        with ExitStack() as resources:
            from .ocr.session import OcrSession

            session = resources.enter_context(
                OcrSession(
                    root,
                    mode=options.ocr_mode,
                    model=options.resolved_ocr_model,
                    decision_provider=options.resolved_decision_provider,
                )
            )
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
            "and detector-local for local decision models or Wolf Defender."
            if isinstance(error, ModuleNotFoundError)
            else str(error) or "Scan interrupted."
        )
        report["errors"].append({"error": message})
    return finish(report, started)
