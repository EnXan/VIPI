"""Check final OCR text with one detector and persist its verdict."""

from concurrent.futures import CancelledError, ThreadPoolExecutor, as_completed
import time

from .evidence import build_evidence, chunks
from .policy import INSTRUCTIONS, POLICY_VERSION, state
from .providers import create_provider
from .providers.prompt_guard import MODEL_DIR
from vipi.storage.detection import DetectionStore
from vipi.cancellation import check_cancelled
from vipi.config import CLOUD_DECISION_PROVIDERS, LOCAL_DETECTORS
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
                }
            ]
            if name == "prompt-guard"
            else chunks(reading["text"])
        )
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


def _check_job(job, provider, error, store, cancel_event):
    """Execute one text check against the already frozen evidence."""
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


def detect(
    evidence,
    *,
    options=None,
    model_dir=MODEL_DIR,
    store=None,
    on_event=None,
    provider_factory=None,
    cancel_event=None,
):
    """Check final OCR evidence, preserving cancellation and partial answers."""
    options = settings(**(options or {}))
    store = store or DetectionStore(on_event=on_event, run_id=evidence["run_id"])
    factory = provider_factory or (lambda name: create_provider(name, model_dir))
    started = time.perf_counter()
    name = options["text_classifier"]
    signals = [name]
    try:
        check_cancelled(cancel_event)
        jobs = jobs_for(evidence, options)
        store.save_document(
            "inputs.json",
            {
                "schema_version": 3,
                "evidence_scope": "final_ocr",
                "policy_version": POLICY_VERSION,
                "instructions": INSTRUCTIONS,
                "options": options,
                "evidence": evidence,
                "jobs": jobs,
            },
        )
        store.emit(
            "detection_started",
            state="running",
            total=len(jobs),
            evidence_scope="final_ocr",
            signals=signals,
        )
        provider, error = None, None
        if jobs:
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
                summary = summarize(
                    [answer],
                    signals,
                    options["thresholds"],
                    evidence_complete=evidence["ocr_complete"],
                )
                answer.update(verdict=summary["verdict"], check_id=store.id)
                store.save_answer(answer)
        check_cancelled(cancel_event)
        answers = sorted(store.results, key=lambda answer: answer["id"])
        summary = summarize(
            answers,
            signals,
            options["thresholds"],
            evidence_complete=evidence["ocr_complete"],
        )
        result = {
            "schema_version": 3,
            "evidence_scope": "final_ocr",
            "run_id": evidence["run_id"],
            "check_id": store.id,
            "policy_version": POLICY_VERSION,
            "input_hash": evidence["input_hash"],
            "ocr_complete": evidence["ocr_complete"],
            "readings": len(evidence["readings"]),
            "thresholds": options["thresholds"],
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


def detect_ocr(ocr, *, options=None, provider_factory=None, on_event=None):
    """Use a typed OCR result directly; persistence follows its artifact location."""
    from vipi.results import DetectionResult

    evidence = build_evidence(ocr.to_dict(), run_id=ocr.run_id, image=ocr.image)
    store = DetectionStore(ocr.artifacts, on_event, run_id=ocr.run_id)
    payload = detect(
        evidence,
        options=options,
        store=store,
        provider_factory=provider_factory,
        on_event=on_event,
    )
    return DetectionResult.from_dict(payload)
