"""Lazy providers: OCR-only operation never imports local detector weights."""

from .jev import Jev
from .openai import Decisions
from .prompt_guard import PromptGuard


def create_provider(name, model_dir):
    return {
        "jev": Jev,
        "openai": Decisions,
        "prompt-guard": lambda: PromptGuard(model_dir),
    }[name]()


def prepare_provider(name, model_dir):
    provider = create_provider(name, model_dir)
    if name != "prompt-guard" and not provider.key:
        key = "TYPESAFE_API_KEY (or JEV_API_KEY)" if name == "jev" else "OPENAI_API_KEY"
        raise ValueError(f"Set {key} in the environment or local .env.")
    return provider
