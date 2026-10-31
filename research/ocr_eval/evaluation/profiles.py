"""Research OCR profiles; the public scanner keeps its release defaults."""

from vipi.ocr.runtime import DEFAULT_BACKEND, threads_per_worker
from vipi.ocr.workers import DEFAULT_WORKERS

DEFAULT_PROFILE = "baseline"
PROFILES = (DEFAULT_PROFILE, "transforms", "adaptive-jev")


def validate_profile(profile):
    if profile not in PROFILES:
        raise ValueError("Choose baseline, transforms or adaptive-jev as the OCR profile.")
    return profile


def engine_factory_for(
    profile=DEFAULT_PROFILE,
    *,
    backend=DEFAULT_BACKEND,
    workers=DEFAULT_WORKERS,
    override=None,
):
    validate_profile(profile)
    if override is not None:
        return override

    def factory(model, directory):
        from research.workbench.model_registry import create_engine

        return create_engine(
            model,
            directory,
            backend=backend,
            threads=threads_per_worker(workers),
            profile=profile,
        )

    return factory
