"""Bounded independent detector scheduling over frozen OCR readings."""

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import time
from pathlib import Path

from .comparison import comparison
from .context import validate_context
from .evidence import build_evidence, chunks, digest, load_evidence
from .policy import INSTRUCTIONS, POLICY_VERSION, state
from .providers import create_provider
from .providers.prompt_guard import MODEL_DIR
from vipi.storage.detection import DetectionStore
from .verdict import probability, summarize, validate_thresholds

TEXT_CLASSIFIERS = ("jev", "openai", "prompt-guard", "compare", "off")


def settings(
    *,
    text_classifier="jev",
    image_check="off",
    context_check="off",
    context=None,
    thresholds=None,
    reuse=True,
):
    if (
        text_classifier not in TEXT_CLASSIFIERS
        or image_check not in {"off", "openai"}
        or context_check not in {"off", "openai"}
    ):
        raise ValueError("Choose supported detector modes.")
    if text_classifier == image_check == context_check == "off":
        raise ValueError("Select at least one detector check.")
    if not isinstance(reuse, bool):
        raise ValueError("reuse must be a boolean.")
    return {
        "text_classifier": text_classifier,
        "image_check": image_check,
        "context_check": context_check,
        "context": validate_context(context),
        "thresholds": validate_thresholds(thresholds),
        "reuse": reuse,
    }


def jobs_for(evidence, options):
    names = (
        ["jev", "openai", "prompt-guard"]
        if options["text_classifier"] == "compare"
        else []
        if options["text_classifier"] == "off"
        else [options["text_classifier"]]
    )
    jobs = []
    for reading in evidence["readings"]:
        for name in names:
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
                else list(chunks(reading["text"]))
            )
            for part in parts:
                jobs.append(
                    {
                        "provider": name,
                        "signal": name,
                        "reading_id": reading["id"],
                        "source_ids": [x["id"] for x in reading["sources"]],
                        **part,
                        "evidence": {"text": part["text"]},
                    }
                )
    if options["image_check"] == "openai":
        jobs.append(
            {
                "provider": "openai",
                "signal": "image",
                "reading_id": None,
                "source_ids": ["input"],
                "evidence": {"kind": "original_image"},
                "partial_context": False,
            }
        )
    if options["context_check"] == "openai":
        # Use the same final OCR text as the text detectors; never include variants.
        joined = json.dumps(
            [{"reading_id": x["id"], "text": x["text"]} for x in evidence["readings"]],
            ensure_ascii=False,
        )
        for part in chunks(joined):
            jobs.append(
                {
                    "provider": "openai",
                    "signal": "context",
                    "reading_id": None,
                    "source_ids": ["input", *[x["id"] for x in evidence["readings"]]],
                    **part,
                    "evidence": {
                        "kind": "original_image_and_final_ocr",
                        "serialized_readings": part["text"],
                    },
                }
            )
    for i, job in enumerate(jobs):
        job["id"] = f"{i + 1:04d}"
    return jobs, [
        *names,
        *(["image"] if options["image_check"] == "openai" else []),
        *(["context"] if options["context_check"] == "openai" else []),
    ]


def cached_answers(directory):
    saved = {}
    for path in sorted(
        (Path(directory) / "detection").glob("*/answers.jsonl"),
        key=lambda x: x.stat().st_mtime,
    ):
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                result = json.loads(line)
                if result.get("status") == "completed":
                    probability(result.get("probability"))
                    saved[result["fingerprint"]] = result
            except (ValueError, KeyError):
                continue
    return saved


def detect(
    evidence,
    image=None,
    *,
    options=None,
    saved_answers=None,
    model_dir=MODEL_DIR,
    store=None,
    on_event=None,
    provider_factory=None,
):
    options = settings(**(options or {}))
    store = store or DetectionStore(on_event=on_event, run_id=evidence["run_id"])
    factory = provider_factory or (lambda name: create_provider(name, model_dir))
    started = time.perf_counter()
    try:
        jobs, signals = jobs_for(evidence, options)
        prepared = {
            "schema_version": 2,
            "evidence_scope": "final_ocr",
            "policy_version": POLICY_VERSION,
            "instructions": INSTRUCTIONS,
            "context_hash": digest(options["context"]),
            "context_available": bool(options["context"].get("task", "").strip()),
            "options": options,
            "evidence": evidence,
            "jobs": jobs,
        }
        store.save_document("inputs.json", prepared)
        store.emit(
            "detection_started",
            state="running",
            total=len(jobs),
            evidence_scope="final_ocr",
            signals=signals,
            context_available=prepared["context_available"],
        )
        saved = (saved_answers or {}) if options["reuse"] else {}
        providers, errors = {}, {}
        for name in dict.fromkeys(x["provider"] for x in jobs):
            try:
                providers[name] = factory(name)
            except Exception as error:
                errors[name] = str(error)

        def work(job):
            provider = providers.get(job["provider"])
            context = {} if job["provider"] == "prompt-guard" else options["context"]
            payload = state(job["evidence"], context)
            with_image = job["signal"] in {"image", "context"}
            fingerprint = digest(
                {
                    "schema_version": 2,
                    "evidence_scope": "final_ocr",
                    "provider": job["provider"],
                    "identity": provider.identity if provider else None,
                    "policy": INSTRUCTIONS,
                    "policy_version": POLICY_VERSION,
                    "signal": job["signal"],
                    "payload": payload,
                    "image": evidence["image_hash"] if with_image else None,
                    "context_hash": prepared["context_hash"],
                }
            )
            base = {
                key: value
                for key, value in job.items()
                if key not in {"text", "evidence"}
            }
            base.update(
                fingerprint=fingerprint,
                policy_version=POLICY_VERSION,
                context_hash=prepared["context_hash"],
                probability=None,
                model=provider.model if provider else None,
                status="error",
                replayed=False,
            )
            if provider and fingerprint in saved:
                old = saved[fingerprint]
                base.update(
                    {
                        key: value
                        for key, value in old.items()
                        if key not in base
                        or key in {"probability", "status", "model", "partial_context"}
                    }
                )
                base.update(
                    replayed=True,
                    replayed_from=old.get("check_id"),
                    latency_seconds=0.0,
                )
                return base
            check_started = time.perf_counter()
            store.emit(
                "check_started", active_check=job["id"], active_signal=job["signal"]
            )
            try:
                if not provider:
                    raise ValueError(errors[job["provider"]])
                if with_image and image is None:
                    raise ValueError(
                        "Original input raster is missing; image check cannot run."
                    )
                answer = provider.check(payload, image if with_image else None)
                if answer.get("status") == "completed":
                    probability(answer.get("probability"))
                base.update(answer)
            except Exception as error:
                base.update(
                    status="error",
                    error=str(error),
                    attempts=getattr(error, "attempts", 0),
                    cost_uncertain=getattr(error, "attempts", 0) > 0,
                )
            base["latency_seconds"] = time.perf_counter() - check_started
            return base

        def save(future):
            answer = future.result()
            if answer["signal"] == "context" and not prepared["context_available"]:
                answer["partial_context"] = True
            single = summarize(
                [answer],
                [answer["signal"]],
                options["thresholds"],
                evidence_complete=evidence["ocr_complete"]
                and (bool(evidence["readings"]) or options["text_classifier"] == "off"),
            )
            answer.update(verdict=single["verdict"], check_id=store.id)
            store.save_answer(answer)

        with (
            ThreadPoolExecutor(max_workers=4, thread_name_prefix="detector-api") as api,
            ThreadPoolExecutor(
                max_workers=1, thread_name_prefix="detector-local"
            ) as local,
        ):
            futures = [
                (local if job["provider"] == "prompt-guard" else api).submit(work, job)
                for job in jobs
            ]
            for future in as_completed(futures):
                save(future)
        answers = sorted(store.results, key=lambda x: x["id"])
        complete = evidence["ocr_complete"] and (
            bool(evidence["readings"]) or options["text_classifier"] == "off"
        )
        summary = summarize(
            answers, signals, options["thresholds"], evidence_complete=complete
        )
        result = {
            "schema_version": 2,
            "evidence_scope": "final_ocr",
            "run_id": evidence["run_id"],
            "check_id": store.id,
            "policy_version": POLICY_VERSION,
            "context_available": prepared["context_available"],
            "context_hash": prepared["context_hash"],
            "input_hash": evidence["input_hash"],
            "ocr_complete": evidence["ocr_complete"],
            "readings": len(evidence["readings"]),
            "missing_text_evidence": not evidence["readings"],
            "thresholds": options["thresholds"],
            "answers": answers,
            **summary,
            "comparison": comparison(answers),
            "elapsed_seconds": time.perf_counter() - started,
        }
        store.save_document("result.json", result)
        store.emit(
            "detection_completed",
            state="completed",
            verdict=result["verdict"],
            review_required=result["review_required"],
            active_check=None,
            active_signal=None,
        )
        return result
    except (Exception, KeyboardInterrupt) as error:
        store.emit(
            "detection_failed",
            state="failed",
            error=str(error) or "Interrupted; partial answers are saved.",
        )
        raise


def detect_saved_run(
    run_directory,
    *,
    options=None,
    model_dir=MODEL_DIR,
    store=None,
    on_event=None,
    provider_factory=None,
):
    """Load persisted evidence for replay; direct checks use detect(evidence)."""
    options = settings(**(options or {}))
    directory = Path(run_directory)
    evidence, image = load_evidence(directory)
    store = store or DetectionStore(directory, on_event)
    return detect(
        evidence,
        image,
        options=options,
        model_dir=model_dir,
        store=store,
        saved_answers=cached_answers(directory) if options["reuse"] else {},
        provider_factory=provider_factory,
    )


def detect_ocr(ocr, *, options=None, provider_factory=None, on_event=None):
    """Use a typed OCR result directly; persistence follows its artifact location."""
    from vipi.results import DetectionResult

    evidence = build_evidence(ocr.to_dict(), run_id=ocr.run_id, image=ocr.image)
    store = DetectionStore(ocr.artifacts, on_event, run_id=ocr.run_id)
    payload = detect(
        evidence,
        ocr.image,
        options=options,
        store=store,
        provider_factory=provider_factory,
    )
    return DetectionResult.from_dict(payload)
