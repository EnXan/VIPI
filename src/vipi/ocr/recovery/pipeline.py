"""Run OCR recognition, recovery, and artifact persistence for one image."""

from concurrent.futures import CancelledError
from pathlib import Path
import time

from vipi.cancellation import check_cancelled
from vipi.config import CLOUD_OCR_MODELS
from vipi.ocr.merge import ASSEMBLY_VERSION
from vipi.ocr.transforms import MAX_INPUT_PIXELS, decode_image
from vipi.storage.files import write_json
from vipi.storage.ocr import RunStore

from .decision_adapters import DecisionsDecider
from .layout import LAYOUT_VERSION
from .probes import recover_resolution
from .selection import select_reading
from .tiles import recover_with_tiles

PROFILE = "adaptive-jev"


def _complete_run(
    original,
    selected,
    selection,
    attempts,
    engine,
    decider,
    store,
    *,
    model,
    backend,
    cancel_event,
    on_result,
    started,
):
    """Merge source tiles, attach optional evaluation, and persist a completed run."""
    write_json(store.directory / "decisions.json", selection["decisions"])
    final_text, final_regions, tile_attempts, tile_recovery = recover_with_tiles(
        original, selected, engine, store, attempts, cancel_event
    )
    all_attempts = [*attempts, *tile_attempts]
    full_page_text = bool(selected["step"].get("full_page_text"))
    if tile_recovery["selected"]:
        assembly_version = ASSEMBLY_VERSION
    elif final_regions and not full_page_text:
        assembly_version = LAYOUT_VERSION
    else:
        assembly_version = None
    result = {
        "run_id": store.id,
        "model": model,
        "ocr_profile": PROFILE,
        "workers": 1,
        "backend": backend,
        "threads_per_worker": 1,
        "input_size": list(original.size),
        "text": final_text,
        "regions": final_regions,
        "variants": [a["step"] for a in all_attempts],
        "assembly_version": assembly_version,
        "preserve_raw_text": (full_page_text or not bool(final_regions))
        and not tile_recovery["selected"],
        "full_page_text": full_page_text,
        "selection": {
            "provider": decider.provider,
            "model": decider.model,
            "selected_attempt": selected["id"],
            **selection,
            "accepted": selection["review_action"] == "accept",
            "candidate_count": len(attempts),
            "tile_recovery": tile_recovery,
        },
    }
    from vipi.ocr.costs import cost_for_result

    result["cost"] = cost_for_result(result)
    check_cancelled(cancel_event)
    if on_result:
        on_result(result)
    result["elapsed_seconds"] = time.perf_counter() - started
    write_json(store.directory / "result.json", result)
    (store.directory / "result.txt").write_text(result["text"], encoding="utf-8")
    store.transition(
        "run_completed",
        state="completed",
        current=None,
        active_steps={},
        total=len(all_attempts),
        completed=len(all_attempts),
        data={
            "text": result["text"],
            "regions": result["regions"],
            "evaluation": result.get("evaluation"),
            "selection": result["selection"],
        },
    )
    return result


def extract(
    image,
    model,
    on_event=None,
    *,
    engine=None,
    engine_factory=None,
    engine_pool=None,
    store=None,
    runs_dir="runs",
    models_dir="models/ocr",
    backend="cpu",
    cancel_event=None,
    on_result=None,
    decider=None,
):
    """Recognize and review OCR candidates, then save the selected reading.

    Engines return native text and regions; the decider assesses image defects
    and compares actual readings. Spatial retries retain incumbent words.
    ``on_result`` can attach evaluation after selection, before persistence.
    Failed and cancelled runs retain completed steps in the supplied run store.
    """
    store = store or RunStore(
        Path(runs_dir), model, on_event, workers=1, backend=backend
    )
    decider = decider or DecisionsDecider()
    started = time.perf_counter()
    attempts = []
    local_engine = None
    try:
        check_cancelled(cancel_event)
        original = decode_image(
            image,
            max_pixels=None if model in CLOUD_OCR_MODELS else MAX_INPUT_PIXELS,
        )
        original.save(store.directory / "input.png")
        store.transition(
            "run_started",
            state="selecting",
            model=model,
            ocr_profile=PROFILE,
            total=1,
            workers=1,
            input_size=list(original.size),
            active_steps={},
        )
        begin = time.perf_counter()
        if engine_pool is not None:
            local_engine = engine_pool.engine()
        elif engine is not None:
            local_engine = engine
        elif engine_factory is not None:
            local_engine = engine_factory(model, Path(models_dir))
        else:
            from vipi.ocr.engines import create_engine

            local_engine = create_engine(
                model,
                Path(models_dir),
                backend=backend,
                threads=1,
            )
        initialization_seconds = time.perf_counter() - begin
        selected, selection = select_reading(
            original,
            model,
            local_engine,
            decider,
            store,
            attempts,
            initialization_seconds,
            cancel_event,
        )
        selected = recover_resolution(
            original,
            selected,
            selection,
            local_engine,
            decider,
            store,
            attempts,
            cancel_event,
        )
        return _complete_run(
            original,
            selected,
            selection,
            attempts,
            local_engine,
            decider,
            store,
            model=model,
            backend=backend,
            cancel_event=cancel_event,
            on_result=on_result,
            started=started,
        )
    except CancelledError:
        store.transition(
            "run_cancelled", state="cancelled", active_steps={}, current=None
        )
        raise
    except (Exception, KeyboardInterrupt) as error:
        if engine_pool is not None and local_engine is not None:
            engine_pool.discard_engine()
        store.transition(
            "run_failed", state="failed", active_steps={}, error=str(error)
        )
        raise
    finally:
        if engine is None and engine_pool is None and local_engine is not None:
            close = getattr(local_engine, "close", None)
            if close:
                close()
