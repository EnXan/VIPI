"""Pinned local weights and overlapping native-token windows, without downloads."""

import importlib.metadata
import json
import re
import threading
import tempfile
from contextlib import contextmanager
from pathlib import Path

from vipi.storage.files import sha256 as file_hash

MODEL_ID = "meta-llama/Llama-Prompt-Guard-2-86M"
MODEL_DIR = "models/detector/prompt-guard-2-86m"
_loaded = {}
_load_lock = threading.Lock()


@contextmanager
def suppress_transformers_progress():
    from transformers.utils import logging

    was_enabled = logging.is_progress_bar_enabled()
    if was_enabled:
        logging.disable_progress_bar()
    try:
        yield
    finally:
        if was_enabled:
            logging.enable_progress_bar()


def model_manifest(directory, *, verify=True):
    directory = Path(directory)
    try:
        manifest = json.loads((directory / "manifest.json").read_text())
    except (OSError, ValueError) as error:
        raise ValueError(
            "Prepare Prompt Guard with 'vipi setup --detector prompt-guard'."
        ) from error
    if (
        not isinstance(manifest, dict)
        or not isinstance(manifest.get("files"), dict)
        or manifest.get("model") != MODEL_ID
        or not re.fullmatch(r"[a-f0-9]{40}", manifest.get("revision", ""))
        or not manifest.get("files")
    ):
        raise ValueError("Invalid Prompt Guard model manifest.")
    for name, expected in manifest["files"].items():
        path = directory / name
        if (
            Path(name).is_absolute()
            or ".." in Path(name).parts
            or not path.is_file()
            or (verify and file_hash(path) != expected)
        ):
            raise ValueError(
                "Prompt Guard files are missing or fail checksum verification."
            )
    return manifest


def prepare_model(directory=MODEL_DIR, *, revision):
    """Download only on explicit preparation, with caller-selected immutable revision."""
    if not re.fullmatch(r"[a-f0-9]{40}", revision):
        raise ValueError("Provide the full 40-character Hugging Face commit SHA.")

    directory = Path(directory)
    if directory.exists() and any(directory.iterdir()):
        manifest = model_manifest(directory)
        if manifest["revision"] != revision:
            raise ValueError("Use a new model directory for another revision.")
        return manifest
    directory.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".prompt-guard-", dir=directory.parent
    ) as temporary:
        staging = Path(temporary)
        manifest = download_snapshot(staging, revision)
        if directory.exists():
            directory.rmdir()  # Only an empty target directory is accepted above.
        staging.replace(directory)
    return manifest


def download_snapshot(directory, revision):
    from huggingface_hub import snapshot_download

    snapshot_download(
        MODEL_ID,
        revision=revision,
        local_dir=directory,
        allow_patterns=[
            "*.json",
            "*.model",
            "*.txt",
            "*.safetensors",
            "LICENSE*",
            "README.md",
            "USE_POLICY*",
        ],
    )
    if not (directory / "config.json").is_file() or not list(
        directory.glob("*.safetensors")
    ):
        raise ValueError("Downloaded snapshot lacks config or safetensors weights.")
    files = {
        str(path.relative_to(directory)): file_hash(path)
        for path in directory.rglob("*")
        if path.is_file() and ".cache" not in path.parts
    }
    manifest = {
        "model": MODEL_ID,
        "revision": revision,
        "license": "Llama 4 Community License",
        "files": files,
    }
    (directory / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def token_windows(tokenizer, text, *, overlap=64):
    backend = tokenizer.backend_tokenizer
    backend.no_truncation()
    backend.no_padding()
    encoded = backend.encode(text, add_special_tokens=False)
    total = len(encoded.ids)
    capacity = 512 - backend.num_special_tokens_to_add(False)
    if not 0 <= overlap < capacity:
        raise ValueError("Invalid native window overlap.")
    if not total:
        return
    encoded.truncate(capacity, stride=overlap)
    for index, window in enumerate([encoded, *encoded.overflowing]):
        start = index * (capacity - overlap)
        end = start + len(window.ids)
        prepared = backend.post_process(window, add_special_tokens=True)
        yield (
            {
                "input_ids": prepared.ids,
                "attention_mask": prepared.attention_mask,
                "token_type_ids": prepared.type_ids,
            },
            {
                "token_start": start,
                "token_end": end,
                "start": window.offsets[0][0] if start else 0,
                "end": window.offsets[-1][1] if end < total else len(text),
                "partial_context": total > capacity,
            },
        )


def native_labels(config):
    labels = {int(k): str(v).upper() for k, v in config.id2label.items()}
    # The official 86M config omits semantic names, so Transformers uses LABEL_0/1.
    # Meta's inference contract defines malicious as column 1:
    # https://github.com/meta-llama/llama-cookbook/blob/main/getting-started/responsible_ai/prompt_guard/inference.py
    if config.num_labels == 2 and labels == {0: "LABEL_0", 1: "LABEL_1"}:
        return {0: "BENIGN", 1: "MALICIOUS"}
    if config.num_labels != 2 or labels != {0: "BENIGN", 1: "MALICIOUS"}:
        raise ValueError("Unexpected native Prompt Guard label mapping.")
    return labels


class PromptGuard:
    name = "prompt-guard"
    model = MODEL_ID
    native = True

    def __init__(self, directory=MODEL_DIR):
        self.directory = Path(directory).resolve()
        self.manifest = model_manifest(self.directory)
        versions = {}
        for name in ("torch", "transformers", "tokenizers"):
            try:
                versions[name] = importlib.metadata.version(name)
            except importlib.metadata.PackageNotFoundError:
                raise ValueError(
                    "Install the detector-local extra to use Prompt Guard."
                ) from None
        self.identity = {
            "model": MODEL_ID,
            "revision": self.manifest["revision"],
            "files": self.manifest["files"],
            "runtime": versions,
            "window_tokens": 512,
            "overlap_tokens": 64,
            "label_mapping": "meta-prompt-guard-2-v1",
            "padding": "disabled-before-windowing",
        }

    def _runtime(self):
        key = (
            str(self.directory),
            self.manifest["revision"],
            tuple(sorted(self.manifest["files"].items())),
        )
        with _load_lock:
            if key not in _loaded:
                import torch
                from transformers import (
                    AutoModelForSequenceClassification,
                    AutoTokenizer,
                )

                tokenizer = AutoTokenizer.from_pretrained(
                    self.directory,
                    local_files_only=True,
                    trust_remote_code=False,
                    use_fast=True,
                )
                if not hasattr(tokenizer, "backend_tokenizer"):
                    raise ValueError(
                        "Prompt Guard requires tokenizer offsets for window provenance."
                    )
                with suppress_transformers_progress():
                    model = AutoModelForSequenceClassification.from_pretrained(
                        self.directory,
                        local_files_only=True,
                        trust_remote_code=False,
                        use_safetensors=True,
                    ).eval()
                labels = native_labels(model.config)
                _loaded[key] = tokenizer, model, torch, labels, threading.Lock()
            return _loaded[key]

    def check(self, state, image=None):
        tokenizer, model, torch, labels, lock = self._runtime()
        text = state["untrusted_evidence"]["text"]
        malicious_id = next(k for k, v in labels.items() if v == "MALICIOUS")
        windows = []
        with lock, torch.inference_mode():
            for inputs, bounds in token_windows(tokenizer, text):
                tensors = {
                    key: torch.tensor([value])
                    for key, value in inputs.items()
                    if key in tokenizer.model_input_names
                }
                scores = torch.softmax(model(**tensors).logits, dim=-1)[0].tolist()
                windows.append(
                    {
                        **bounds,
                        "probability": scores[malicious_id],
                        "native_label": labels[
                            max(range(len(scores)), key=scores.__getitem__)
                        ],
                    }
                )
        if not windows:
            return {"status": "error", "error": "No native tokens in OCR reading."}
        return {
            "status": "completed",
            "probability": max(x["probability"] for x in windows),
            "native_label": max(windows, key=lambda x: x["probability"])[
                "native_label"
            ],
            "question_id": None,
            "model": MODEL_ID,
            "revision": self.manifest["revision"],
            "windows": windows,
            "partial_context": len(windows) > 1,
            "input_tokens": sum(x["token_end"] - x["token_start"] for x in windows),
            "estimated_usd": 0.0,
            "cost_scope": "API fees only; excludes local compute",
            "raw": {"windows": windows, "labels": labels},
            "attempts": 1,
            "cost_uncertain": False,
        }
