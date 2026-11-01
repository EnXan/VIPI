"""Pinned Clef/d1 inference shared by OCR review and injection detection."""

import hashlib
import importlib.util
from importlib import import_module
from functools import partial
import json
from pathlib import Path
import sys
import threading

MODELS = json.loads(Path(__file__).with_name("decision_models.json").read_text())
_loaded = {}
_load_lock = threading.Lock()


def validate_model(name, directory):
    directory = Path(directory)
    metadata = MODELS[name]
    ready = directory / "READY.json"
    if (
        not ready.is_file()
        or json.loads(ready.read_text()).get("revision") != metadata["revision"]
    ):
        raise ValueError(
            f"Local {name} weights are missing. Run vipi setup with the same --modus and --ocr-mode."
        )
    for filename, expected in metadata["code"].items():
        path = directory / filename
        if (
            not path.is_file()
            or hashlib.sha256(path.read_bytes()).hexdigest() != expected
        ):
            raise ValueError(
                f"Local {name} code does not match its pinned revision; rerun vipi setup."
            )
    index = directory / "model.safetensors.index.json"
    weights = (
        set(json.loads(index.read_text())["weight_map"].values())
        if index.is_file()
        else {"model.safetensors"}
    )
    if name == "clef":
        weights.add("joint_head.safetensors")
    for filename in ["config.json", "tokenizer_config.json", *weights]:
        if not (directory / filename).is_file():
            raise ValueError(
                f"Incomplete local {name} model: missing {filename}. Run vipi setup."
            )
    return metadata


def prepare_model(name, directory):
    from huggingface_hub import snapshot_download

    metadata = MODELS[name]
    directory = Path(directory)
    snapshot_download(
        metadata["repository"],
        revision=metadata["revision"],
        local_dir=directory,
        allow_patterns=[
            "*.json",
            "*.py",
            "*.safetensors",
            "*.model",
            "*.jinja",
            "LICENSE*",
        ],
    )
    ready = directory / "READY.json"
    ready.write_text(json.dumps(metadata, indent=2))
    try:
        validate_model(name, directory)
    except Exception:
        ready.unlink(missing_ok=True)
        raise


class LocalDecisionModel:
    """Load verified, prepared Clef/d1 files and reuse their inference runtime."""

    def __init__(self, name, directory):
        self.name = name
        self.directory = Path(directory).resolve()
        metadata = validate_model(name, self.directory)
        self.model = metadata["repository"]
        self.identity = {
            "model": self.model,
            "revision": metadata["revision"],
            "code": metadata["code"],
            "runtime_policy": "local-v1-mps-fp16-query-chunks-serial-vision",
        }

    def _runtime(self):
        key = (self.name, str(self.directory), self.identity["revision"])
        with _load_lock:
            if key not in _loaded:
                import torch

                if torch.cuda.is_available():
                    device, dtype = "cuda", torch.bfloat16
                elif torch.backends.mps.is_available():
                    device, dtype = "mps", torch.float16
                else:
                    device, dtype = "cpu", torch.float32
                if self.name == "d1":
                    from transformers import AutoModel

                    model = (
                        AutoModel.from_pretrained(
                            self.directory,
                            local_files_only=True,
                            trust_remote_code=True,
                            dtype=dtype,
                        )
                        .to(device)
                        .eval()
                    )
                    if device == "mps":
                        from .local_attention import (
                            causal_attention,
                            serial_vision_forward,
                        )

                        hybrid = import_module(
                            model.__class__.__module__.rsplit(".", 1)[0] + ".hybrid"
                        )
                        hybrid.causal_attention = partial(
                            causal_attention, query_chunk=hybrid.CHUNK
                        )
                        tower = model.model.vision_tower
                        tower.forward = partial(serial_vision_forward, tower.forward)
                    runtime = (model, None, None)
                else:
                    module_name = "vipi_pinned_clef_" + self.identity["revision"]
                    spec = importlib.util.spec_from_file_location(
                        module_name, self.directory / "joint_schema_model.py"
                    )
                    module = importlib.util.module_from_spec(spec)
                    sys.modules[module_name] = module
                    spec.loader.exec_module(module)
                    model, processor = module.load_release_model(
                        self.directory,
                        device=device,
                        dtype=dtype,
                        local_files_only=True,
                    )
                    runtime = (model, processor, module)
                _loaded[key] = (*runtime, torch, threading.Lock())
            return _loaded[key]

    def ask(self, state, questions, images=None):
        model, processor, module, torch, lock = self._runtime()
        with lock, torch.inference_mode():
            try:
                if self.name == "d1":
                    return model.system_one(state, questions, images=images or None)
                request = {
                    "model": self.model,
                    "state": state,
                    "questions": questions,
                    "images": images or [],
                }
                # The upstream encoder truncates at max_length. Encode completely
                # first and reject inputs exceeding the actual backbone context.
                encoded = module.encode_record(
                    processor.tokenizer,
                    request,
                    max_length=sys.maxsize,
                    processor=processor,
                )
                config = model.language_model.config
                config = getattr(config, "text_config", config)
                limit = config.max_position_embeddings
                if len(encoded.input_ids) > limit:
                    raise ValueError(
                        f"Clef input exceeds its model context of {limit} tokens."
                    )
                return module.systemone(model, processor, request, max_length=limit)
            finally:
                if next(model.parameters()).device.type == "mps":
                    torch.mps.synchronize()
                    torch.mps.empty_cache()
