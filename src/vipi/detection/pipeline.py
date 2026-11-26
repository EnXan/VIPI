"""Check scan evidence with one detector and persist its verdict."""

from concurrent.futures import CancelledError, ThreadPoolExecutor, as_completed
from io import BytesIO
import time

from .decoding import decoded
from .evidence import build_evidence, chunks, windows
from .policy import INSTRUCTIONS, POLICY_VERSION, state
from .providers import create_provider
from .providers.prompt_guard import MODEL_DIR
from vipi.storage.detection import DetectionStore
from vipi.cancellation import check_cancelled
from vipi.transparency import READINGS
from vipi.config import (
    CLOUD_DECISION_PROVIDERS,
    LOCAL_DECISION_PROVIDERS,
    LOCAL_DETECTORS,
)
from .verdict import probability, summarize, validate_thresholds

TEXT_PROVIDERS = (*CLOUD_DECISION_PROVIDERS, *LOCAL_DETECTORS)


def settings(*, text_classifier="jev", thresholds=None):
    if text_classifier not in TEXT_PROVIDERS:
        raise ValueError("Choose a supported text detector.")
    return {
        "text_classifier": text_classifier,
        "thresholds": validate_thresholds(thresholds),
    }


def jobs_for(evidence, options):
    name = options["text_classifier"]
    jobs = []
    for reading in evidence["readings"]:
        parts = (
            [
                {
                    "text": reading["text"],
                    "start": 0,
                    "end": len(reading["text"]),
                    "partial_context": False,
                    "kind": "text",
                }
            ]
            if name == "prompt-guard"
            else list(chunks(reading["text"]))
        )
        if name in LOCAL_DECISION_PROVIDERS:
            parts += list(windows(reading["text"]))
        parts += list(decoded(reading["text"]))
        for part in parts:
            jobs.append(
                {
                    "id": f"{len(jobs) + 1:04d}",
                    "provider": name,
                    "signal": name,
                    "reading_id": reading["id"],
                    "source_ids": [source["id"] for source in reading["sources"]],
                    **part,
                    "evidence": {"text": part["text"]},
                }
            )
    return jobs


def _image_job(name, index, view=None):
    return {
        "id": f"{index:04d}",
        "provider": name,
        "signal": name,
        "kind": "image",
        **({"view": view} if view is not None else {}),
        "evidence": {"image": "input.png"},
    }


def _check_job(job, provider, error, store, cancel_event, load_image=None):
    """Execute one check against the already frozen evidence."""
    check_cancelled(cancel_event)
    answer = {
        key: value for key, value in job.items() if key not in {"text", "evidence"}
    }
    answer.update(
        policy_version=POLICY_VERSION,
        probability=None,
        model=provider.model if provider else None,
        status="error",
    )
    started = time.perf_counter()
    store.emit("check_started", active_check=job["id"], active_signal=job["signal"])
    check_cancelled(cancel_event)
    try:
        if provider is None:
            raise ValueError(error)
        if job["kind"] == "image":
            result = provider.check_image(load_image())
        else:
            result = provider.check(state(job["evidence"]))
        if result.get("status") == "completed":
            probability(result.get("probability"))
        answer.update(result)
    except Exception as failure:
        answer.update(
            status="error",
            error=str(failure),
            attempts=getattr(failure, "attempts", 0),
            cost_uncertain=getattr(failure, "attempts", 0) > 0,
        )
    answer["latency_seconds"] = time.perf_counter() - started
    return answer


def _save_answer(store, answer, signals, thresholds, evidence_complete):
    single = summarize(
        [answer],
        signals,
        thresholds,
        evidence_complete=evidence_complete or answer["kind"] == "image",
    )
    answer.update(verdict=single["verdict"], check_id=store.id)
    store.save_answer(answer)


def detect(
    evidence,
    *,
    options=None,
    model_dir=MODEL_DIR,
    store=None,
    on_event=None,
    provider_factory=None,
    cancel_event=None,
    load_images=(),
):
    """Check the requested evidence, preserving cancellation and partial answers.

    ``load_images`` lists ``(view, loader)`` pairs for the whole-image check
    that follows a text check without a finding. Images are checked in order
    until one detects; ``view`` is None for an image without transparency views.
    """
    options = settings(**(options or {}))
    incomplete = evidence.get("incomplete", [])
    evidence_complete = evidence["ocr_complete"] is not False and not incomplete
    store = store or DetectionStore(on_event=on_event, run_id=evidence["run_id"])
    factory = provider_factory or (lambda name: create_provider(name, model_dir))
    started = time.perf_counter()
    name = options["text_classifier"]
    signals = [name]
    scope = evidence.get("scope", "final_ocr")
    check_image_after_text = bool(load_images)
    thresholds = options["thresholds"]
    try:
        check_cancelled(cancel_event)
        jobs = jobs_for(evidence, options)
        inputs = {
            "schema_version": 3,
            "evidence_scope": scope,
            "policy_version": POLICY_VERSION,
            "instructions": INSTRUCTIONS,
            "options": options,
            "evidence": evidence,
            "jobs": jobs,
        }
        if check_image_after_text:
            inputs["image_check_after_text"] = True
        store.save_document("inputs.json", inputs)
        store.emit(
            "detection_started",
            state="running",
            total=len(jobs),
            evidence_scope=scope,
            signals=signals,
        )
        provider, error = None, None
        if jobs or check_image_after_text:
            check_cancelled(cancel_event)
            try:
                provider = factory(name)
            except Exception as failure:
                error = str(failure)
        with ThreadPoolExecutor(
            max_workers=1 if name == "prompt-guard" else 4,
            thread_name_prefix="detector",
        ) as pool:
            futures = [
                pool.submit(_check_job, job, provider, error, store, cancel_event)
                for job in jobs
            ]
            for future in as_completed(futures):
                try:
                    answer = future.result()
                except CancelledError:
                    continue
                _save_answer(store, answer, signals, thresholds, evidence_complete)
        check_cancelled(cancel_event)
        answers = sorted(store.results, key=lambda answer: answer["id"])
        summary = summarize(
            answers,
            signals,
            thresholds,
            evidence_complete=evidence_complete,
        )
        if check_image_after_text and summary["verdict"] != "injection_detected":
            scope += "_and_image"
            inputs["evidence_scope"] = scope
            for view, load_image in load_images:
                job = _image_job(name, len(jobs) + 1, view)
                jobs.append(job)
                store.save_document("inputs.json", inputs)
                store.emit("image_check_scheduled", total=len(jobs))
                answer = _check_job(
                    job, provider, error, store, cancel_event, load_image
                )
                _save_answer(store, answer, signals, thresholds, evidence_complete)
                answers.append(answer)
                check_cancelled(cancel_event)
                summary = summarize(
                    answers, signals, thresholds, evidence_complete=evidence_complete
                )
                if summary["verdict"] == "injection_detected":
                    break
        result = {
            "schema_version": 3,
            "evidence_scope": scope,
            "run_id": evidence["run_id"],
            "check_id": store.id,
            "policy_version": POLICY_VERSION,
            "input_hash": evidence["input_hash"],
            "ocr_complete": evidence["ocr_complete"],
            "incomplete": incomplete,
            "readings": len(evidence["readings"]),
            "thresholds": thresholds,
            "answers": answers,
            **summary,
            "elapsed_seconds": time.perf_counter() - started,
        }
        store.save_document("result.json", result)
        store.emit(
            "detection_completed",
            state="completed",
            verdict=result["verdict"],
            injection_probability=result["injection_probability"],
            active_check=None,
            active_signal=None,
        )
        return result
    except CancelledError:
        store.emit(
            "detection_cancelled",
            state="cancelled",
            active_check=None,
            active_signal=None,
        )
        raise
    except (Exception, KeyboardInterrupt) as error:
        store.emit(
            "detection_failed",
            state="failed",
            error=str(error) or "Interrupted; partial answers are saved.",
        )
        raise


def detect_ocr(
    ocr,
    *,
    options=None,
    provider_factory=None,
    on_event=None,
    source_text=None,
    metadata_text=None,
    barcode_text=None,
    openstego_texts=None,
    views=None,
    incomplete=(),
    text_only=False,
):
    """Use a typed OCR result directly; persistence follows its artifact location.

    ``source_text`` adds an SVG source reading (ADR 0078), ``metadata_text``
    an image metadata reading (ADR 0083) and ``barcode_text`` decoded code
    payloads (ADR 0084). ``openstego_texts`` maps each OpenStego layout to its
    reading (ADRs 0086 and 0087).
    Reasons in ``incomplete`` prevent a clean verdict.
    ``views`` maps transparency views other than white to their OCR results
    (ADR 0085); their texts are readings and their rasters are image checks.
    """
    from vipi.results import DetectionResult

    evidence = build_evidence(
        ocr.to_dict(),
        run_id=ocr.run_id,
        image=ocr.image,
        source_text=source_text,
        metadata_text=metadata_text,
        barcode_text=barcode_text,
        openstego_texts=openstego_texts,
        view_texts=(
            {READINGS[name]: result.text for name, result in views.items()}
            if views is not None
            else None
        ),
        incomplete=incomplete,
    )
    store = DetectionStore(ocr.artifacts, on_event, run_id=ocr.run_id)
    check_image = (
        not text_only
        and (options or {}).get("text_classifier", "jev") in CLOUD_DECISION_PROVIDERS
    )

    def loader(result):
        def load_image():
            from vipi.images import decode_image

            if result.image is None:
                raise ValueError("The input image is unavailable for image detection.")
            return decode_image(BytesIO(result.image), max_pixels=None)

        return load_image

    load_images = []
    if check_image:
        load_images.append(("white" if views is not None else None, loader(ocr)))
        load_images += [
            (name, loader(result)) for name, result in (views or {}).items()
        ]

    payload = detect(
        evidence,
        options=options,
        store=store,
        provider_factory=provider_factory,
        on_event=on_event,
        load_images=load_images,
    )
    return DetectionResult.from_dict(payload)
