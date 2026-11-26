"""Lazy providers: OCR-only operation never imports local detector weights."""

from .jev import Jev
from .openai import Decisions
from .wolf_defender import WolfDefender
from vipi.config import CLOUD_DECISION_PROVIDERS, LOCAL_DECISION_PROVIDERS


def create_provider(name, model_dir):
    """Construct the selected adapter without downloading models."""
    if name in LOCAL_DECISION_PROVIDERS:
        from pathlib import Path
        from .local import LocalDecisionProvider

        return LocalDecisionProvider(name, Path(model_dir).parent / "decisions" / name)
    return {
        "jev": Jev,
        "openai": Decisions,
        "wolf-defender": lambda: WolfDefender(model_dir),
    }[name]()


def prepare_provider(name, model_dir):
    provider = create_provider(name, model_dir)
    if name in CLOUD_DECISION_PROVIDERS and not provider.key:
        key = "TYPESAFE_API_KEY (or JEV_API_KEY)" if name == "jev" else "OPENAI_API_KEY"
        raise ValueError(f"Set {key} in the environment or local .env.")
    return provider
