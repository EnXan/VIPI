"""Parallel views, with adjust -> OCR -> persist ordering inside each worker."""

from concurrent.futures import CancelledError, ThreadPoolExecutor, wait
from dataclasses import asdict
import json
from queue import Empty, Queue
import re
import threading
import time
from pathlib import Path

import cv2

from .engines import create_engine
from .merge import ASSEMBLY_VERSION, assemble
from .models import DEFAULT_MODEL, sha256
from vipi.storage.ocr import RunStore, write_json
from vipi.cancellation import check_cancelled
from .transforms import (
    MISTRAL_OCR_PROFILE,
    OCR_PROFILE,
    apply_filter,
    decode_image,
    production_passes_for_size,
    render_view,
)
from .workers import DEFAULT_WORKERS, worker_count
from .runtime import DEFAULT_BACKEND, threads_per_worker, validate_backend
from vipi.config import MISTRAL_OCR_MODEL


def extract(
    image,
    model=DEFAULT_MODEL,
    on_event=None,
    *,
    runs_dir="runs",
    models_dir="models/ocr",
    engine=None,
    engine_factory=None,
    engine_pool=None,
    store=None,
    workers=DEFAULT_WORKERS,
    on_result=None,
    backend=DEFAULT_BACKEND,
    cancel_event=None,
):
    workers = worker_count(workers)
    validate_backend(model, backend)
    threads = threads_per_worker(workers)
    # Views already run in parallel; nested OpenCV pools compete with OCR threads.
    cv2.setNumThreads(1)
    if engine is not None and (workers != 1 or engine_factory is not None):
        raise ValueError("A supplied engine requires workers=1 and no engine factory.")
    if engine_pool is not None and (
        engine is not None
        or engine_factory is not None
        or (model, Path(models_dir).resolve(), workers, backend)
        != (
            engine_pool.model,
            engine_pool.directory,
            engine_pool.workers,
            engine_pool.backend,
        )
    ):
        raise ValueError(
            "The engine pool must match the run's model, workers and backend."
        )
    store = store or RunStore(
        Path(runs_dir), model, on_event, workers=workers, backend=backend
    )
    stop = threading.Event()
    started = time.perf_counter()
    try:
        check_cancelled(cancel_event)
        original = decode_image(image)
        original.save(store.directory / "input.png", format="PNG")
        passes = production_passes_for_size(*original.size)
        ocr_profile = OCR_PROFILE
        if model == MISTRAL_OCR_MODEL:
            passes = passes[:1]
            ocr_profile = MISTRAL_OCR_PROFILE
        store.transition(
            "run_started",
            state="preparing",
            model=model,
            ocr_profile=ocr_profile,
            total=len(passes),
            input_size=list(original.size),
            workers=workers,
            backend=backend,
            threads_per_worker=threads,
            active_steps={
                str(i): {"state": "preparing", "step": None}
                for i in range(1, workers + 1)
            },
        )
        pending = Queue()
        for index, (view, filter_name) in enumerate(passes, 1):
            pending.put((index, view, filter_name))

        def work(worker_id):
            try:
                check_cancelled(cancel_event)
                # Stateful OCR adapters are never shared between workers.
                if engine_pool is not None:
                    local_engine = engine_pool.engine()
                elif engine is not None:
                    local_engine = engine
                elif engine_factory is not None:
                    local_engine = engine_factory(model, Path(models_dir))
                else:
                    local_engine = create_engine(
                        model, Path(models_dir), backend=backend, threads=threads
                    )
                while not stop.is_set():
                    check_cancelled(cancel_event)
                    try:
                        index, view, name = pending.get_nowait()
                    except Empty:
                        return
                    if stop.is_set():
                        return
                    step_id = f"{index:04d}"
                    current = {
                        "id": step_id,
                        "index": index,
                        "worker_id": worker_id,
                        "view_id": view.id,
                        "filter": name,
                        "width": view.width,
                        "height": view.height,
                        "label": f"{view.id} · {name}",
                    }
                    store.advance(worker_id, "step_started", "transforming", current)
                    transform_started = time.perf_counter()
                    base = render_view(original, view)
                    raster = apply_filter(base, name)
                    transform_seconds = time.perf_counter() - transform_started
                    relative_image = f"images/{step_id}.png"
                    save_started = time.perf_counter()
                    raster.save(store.directory / relative_image, format="PNG")
                    raster_sha256 = sha256(store.directory / relative_image)
                    image_save_seconds = time.perf_counter() - save_started
                    current = {
                        **current,
                        "image": relative_image,
                    }
                    store.advance(worker_id, "image_ready", "transforming", current)
                    check_cancelled(cancel_event)
                    store.advance(worker_id, "ocr_started", "ocr", current)
                    ocr_started = time.perf_counter()
                    recognized = local_engine.recognize(raster)
                    ocr_seconds = time.perf_counter() - ocr_started
                    for region in recognized["regions"]:
                        region["input_polygon"] = view.map_polygon(region["polygon"])
                    store.advance(worker_id, "saving", "saving", current)
                    transformation = asdict(view)
                    transformation["to_input"] = [list(row) for row in view.to_input]
                    transformation["crop"] = list(view.crop) if view.crop else None
                    step = {
                        **current,
                        "transformation": transformation,
                        "raster_sha256": raster_sha256,
                        **recognized,
                        "timing": {
                            "transform_seconds": transform_seconds,
                            "image_save_seconds": image_save_seconds,
                            "ocr_seconds": ocr_seconds,
                        },
                    }
                    store.complete_step(worker_id, step)
            except CancelledError:
                stop.set()
                raise
            except (Exception, KeyboardInterrupt):
                stop.set()
                if engine_pool is not None:
                    engine_pool.discard_engine()
                raise

        pool = (
            engine_pool.executor
            if engine_pool is not None
            else ThreadPoolExecutor(max_workers=workers, thread_name_prefix="ocr")
        )
        try:
            futures = [pool.submit(work, i) for i in range(1, workers + 1)]
            for future in futures:
                future.result()
        finally:
            stop.set()
            # Drain in-flight OCR before emitting a terminal event or releasing the run.
            if engine_pool is None:
                pool.shutdown(wait=True, cancel_futures=True)
            else:
                wait(futures)
        check_cancelled(cancel_event)
        steps = store.snapshot()["variants"]
        store.transition(
            "assembling", state="assembling", active_steps={}, completed=len(steps)
        )
        text, regions = assemble(steps)
        result = {
            "run_id": store.id,
            "model": model,
            "ocr_profile": ocr_profile,
            "workers": workers,
            "backend": backend,
            "threads_per_worker": threads,
            "text": text,
            "input_size": list(original.size),
            "regions": regions,
            "variants": steps,
            "assembly_version": ASSEMBLY_VERSION,
        }
        check_cancelled(cancel_event)
        if on_result is not None:
            on_result(result)
        check_cancelled(cancel_event)
        result["elapsed_seconds"] = time.perf_counter() - started
        write_json(store.directory / "result.json", result)
        (store.directory / "result.txt").write_text(text, encoding="utf-8")
        store.transition(
            "run_completed",
            state="completed",
            current=None,
            active_steps={},
            data={
                "text": text,
                "regions": regions,
                "evaluation": result.get("evaluation"),
            },
            completed=len(steps),
        )
        return result
    except CancelledError:
        store.transition(
            "run_cancelled",
            state="cancelled",
            active_steps={},
            current=None,
            completed=store.status["completed"],
        )
        raise
    except (Exception, KeyboardInterrupt) as error:
        store.transition(
            "run_failed",
            state="failed",
            active_steps={},
            error=str(error),
            completed=store.status["completed"],
        )
        raise


def reassemble(run_id: str, *, runs_dir="runs", on_result=None):
    """Update only a completed result using its persisted OCR observations."""
    if not re.fullmatch(r"[a-f0-9]{32}", run_id):
        raise ValueError("Invalid run ID.")
    directory = Path(runs_dir) / run_id
    status = json.loads((directory / "status.json").read_text(encoding="utf-8"))
    if status["state"] != "completed":
        raise ValueError("Only completed runs can be reassembled.")
    steps = [
        json.loads(line)
        for line in (directory / "steps.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    if len(steps) != status["total"] or len(steps) != status["completed"]:
        raise ValueError("Saved steps are incomplete; final result was not changed.")
    steps.sort(key=lambda step: step.get("index", int(step["id"])))
    result = json.loads((directory / "result.json").read_text(encoding="utf-8"))
    result["text"], result["regions"] = assemble(steps)
    result["variants"] = steps
    result["assembly_version"] = ASSEMBLY_VERSION
    if on_result is not None:
        on_result(result)
    write_json(directory / "result.json", result)
    (directory / "result.txt").write_text(result["text"], encoding="utf-8")
    store = RunStore.restore(directory)
    store.emit(
        "run_completed",
        text=result["text"],
        regions=result["regions"],
        evaluation=result.get("evaluation"),
        completed=len(steps),
    )
    return result
