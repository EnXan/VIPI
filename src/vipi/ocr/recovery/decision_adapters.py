"""Serialize and send OCR decision requests to their selected providers."""

import base64
from io import BytesIO
import json
import math
import time
import urllib.error

from PIL import Image, ImageOps

from vipi.config import JEV_MODEL, api_key
from vipi.detection.providers.http import post_json
from vipi.ocr.costs import decisions_estimated_usd
from vipi.storage.files import write_json

from .decisions import _AdaptiveDecider, read_choice

OPENAI_PATCH_SIZE = 32
OPENAI_MAX_IMAGE_PATCHES = 30_000
LOCAL_MODE_PREVIEW_LIMITS = {
    "speed": 512,
    "fast": 512,
    "balanced": 1024,
    "quality": None,
}


def decision_preview(image, maximum=1568):
    """Prepare a bounded visual preview without changing the OCR raster."""
    preview = image.convert("RGB").copy()
    if maximum is not None:
        preview.thumbnail((maximum, maximum), Image.Resampling.LANCZOS)
    return ImageOps.expand(
        preview,
        (0, 0, max(0, 280 - preview.width), max(0, 280 - preview.height)),
        fill="white",
    )


def local_preview_maximum(mode, device, image_count):
    """Apply the local mode target and measured MPS safety ceiling."""
    if mode not in LOCAL_MODE_PREVIEW_LIMITS:
        raise ValueError(f"Unsupported local OCR mode: {mode}")
    maximum = LOCAL_MODE_PREVIEW_LIMITS[mode]
    if device == "mps":
        hardware_maximum = 1024 if image_count == 1 else 512
        return hardware_maximum if maximum is None else min(maximum, hardware_maximum)
    return maximum


def openai_decision_image(image):
    """Keep full-size input unless it exceeds OpenAI's image patch limit."""
    raster = image.convert("RGB")
    width, height = raster.size

    def patch_count(size):
        width, height = size
        return math.ceil(width / OPENAI_PATCH_SIZE) * math.ceil(
            height / OPENAI_PATCH_SIZE
        )

    if patch_count(raster.size) <= OPENAI_MAX_IMAGE_PATCHES:
        return raster

    scale = math.sqrt(OPENAI_MAX_IMAGE_PATCHES / patch_count(raster.size))
    while True:
        target = (max(1, int(width * scale)), max(1, int(height * scale)))
        if patch_count(target) <= OPENAI_MAX_IMAGE_PATCHES:
            return raster.resize(target, Image.Resampling.LANCZOS)
        scale *= 0.99


class JevDecider(_AdaptiveDecider):
    """Send visual OCR questions to Jev and save reproducible request records."""

    provider = "jev"

    def __init__(self, model=JEV_MODEL, *, timeout=60, transport=post_json):
        self.model = model
        self.timeout = timeout
        self.transport = transport
        self.key = api_key("TYPESAFE_API_KEY", "JEV_API_KEY")

    def _ask(
        self,
        state,
        questions,
        images,
        directory,
    ):
        """Send an image-bearing question bundle to Jev and save the exchange."""
        assets = {}
        for reference, image in images.items():
            full_size = image.convert("RGB")
            directory.mkdir(parents=True, exist_ok=True)
            full_size.save(directory / (reference.strip("<>") + ".png"), format="PNG")
            buffer = BytesIO()
            full_size.save(buffer, format="PNG")
            assets[reference] = {
                "type": "image",
                "format": "png",
                "data_base64": base64.b64encode(buffer.getvalue()).decode(),
            }
        key = self.key
        if not key:
            raise ValueError("Set TYPESAFE_API_KEY or JEV_API_KEY to use adaptive-jev.")
        payload = {
            "model": self.model,
            "state": state,
            "questions": questions,
            "assets": assets,
        }
        write_json(
            directory / "request.json",
            {
                **payload,
                "assets": {k: {"type": "image", "format": "png"} for k in assets},
            },
        )
        started = time.perf_counter()
        try:
            response, metadata = self.transport(
                "https://api.typesafe.ai/v1/systemone",
                key,
                payload,
                timeout=self.timeout,
                headers={"TypeSafe-Danger-Zone-Images": "true"},
            )
        except Exception as error:
            detail = {"type": type(error).__name__, "message": str(error)}
            if isinstance(error, urllib.error.HTTPError):
                detail.update(
                    http_status=error.code, body=error.read().decode(errors="replace")
                )
            write_json(
                directory / "error.json",
                {**detail, "elapsed_seconds": time.perf_counter() - started},
            )
            raise
        record = {
            "response": response,
            "elapsed_seconds": time.perf_counter() - started,
            "attempts": metadata.get("attempts", 1),
            "estimated_usd": None,
        }
        write_json(directory / "response.json", record)
        for name, question in questions.items():
            read_choice(response, name, question["criteria"])
        return record


class LocalDecider(_AdaptiveDecider):
    """Answer visual OCR questions with a prepared Clef or d1 runtime."""

    def __init__(self, name, directory, *, mode="quality", runtime=None):
        from vipi.local_decisions import LocalDecisionModel

        self.runtime = runtime or LocalDecisionModel(name, directory)
        self.provider = name
        self.model = self.runtime.model
        self.mode = mode

    def _ask(
        self,
        state,
        questions,
        images,
        directory,
    ):
        """Resize local previews by mode and device, then ask the local model."""
        directory.mkdir(parents=True, exist_ok=True)
        previews = []
        device = self.runtime.device
        maximum = local_preview_maximum(self.mode, device, len(images))
        for reference, image in images.items():
            preview = decision_preview(image, maximum)
            preview.save(directory / (reference.strip("<>") + ".png"))
            previews.append(preview)
        local_state = {**state, "image_order": list(images)}
        write_json(
            directory / "request.json",
            {
                "state": local_state,
                "questions": questions,
                "images": list(images),
                "ocr_mode": self.mode,
                "decision_device": device,
                "preview_maximum": maximum,
                "submitted_image_sizes": {
                    reference: list(image.size)
                    for reference, image in zip(images, previews)
                },
            },
        )
        started = time.perf_counter()
        response = self.runtime.ask(local_state, questions, previews)
        for name, question in questions.items():
            read_choice(response, name, question["criteria"])
        record = {
            "response": response,
            "elapsed_seconds": time.perf_counter() - started,
            "attempts": 1,
            "estimated_usd": 0.0,
            "execution_mode": "local",
        }
        write_json(directory / "response.json", record)
        return record


class DecisionsDecider(_AdaptiveDecider):
    """Send visual OCR questions to OpenAI Decisions and record usage."""

    provider = "openai-decisions"

    def __init__(self, model="gpt-6-luna", *, timeout=60, transport=post_json):
        self.model = model
        self.timeout = timeout
        self.key = api_key("OPENAI_API_KEY")
        self.transport = transport

    def _ask(
        self,
        state,
        questions,
        images,
        directory,
    ):
        """Send provider-sized PNG assets and save request, response and usage."""
        content = [
            {
                "type": "input_text",
                "text": json.dumps(state, ensure_ascii=False, sort_keys=True),
            }
        ]
        saved_request = {"state": state, "images": [], "questions": []}
        directory.mkdir(parents=True, exist_ok=True)
        # Full-size PNGs preserve pixel dimensions and avoid the local preview policy.
        for reference, image in images.items():
            original_size = image.size
            full_size = openai_decision_image(image)
            resized_for_patch_limit = full_size.size != original_size
            filename = reference.strip("<>") + ".png"
            full_size.save(directory / filename, format="PNG")
            buffer = BytesIO()
            full_size.save(buffer, format="PNG")
            content.extend(
                [
                    {"type": "input_text", "text": f"Image asset {reference}:"},
                    {
                        "type": "input_image",
                        "image_url": "data:image/png;base64,"
                        + base64.b64encode(buffer.getvalue()).decode("ascii"),
                        "detail": "original",
                    },
                ]
            )
            saved_request["images"].append(
                {
                    "reference": reference,
                    "file": filename,
                    "format": "png",
                    "original_size": original_size,
                    "submitted_size": full_size.size,
                    "resized_for_patch_limit": resized_for_patch_limit,
                    "detail": "original",
                }
            )
        api_questions = []
        for name, question in questions.items():
            choices = [
                {
                    "value": value,
                    "description": (
                        option.get("description", str(option))
                        if isinstance(option, dict)
                        else str(option)
                    ),
                }
                for value, option in question["criteria"].items()
            ]
            api_questions.append(
                {
                    "type": "choice",
                    "name": name,
                    "instructions": question["instructions"],
                    "choices": choices,
                }
            )
            saved_request["questions"].append(api_questions[-1])
        payload = {
            "model": self.model,
            "input": [{"role": "user", "content": content}],
            "questions": api_questions,
        }
        write_json(directory / "request.json", saved_request)
        if not self.key:
            raise ValueError("Set OPENAI_API_KEY to use adaptive Decisions.")
        started = time.perf_counter()
        try:
            raw, meta = self.transport(
                "https://api.openai.com/v1/decisions",
                self.key,
                payload,
                timeout=self.timeout,
            )
        except Exception as error:
            write_json(
                directory / "error.json",
                {
                    "type": type(error).__name__,
                    "message": str(error),
                    "elapsed_seconds": time.perf_counter() - started,
                },
            )
            raise
        answers = {}
        for answer in raw.get("answers", []):
            if answer.get("type") == "refusal":
                raise ValueError(f"Decisions refused question: {answer.get('name')}")
            answers[answer.get("name")] = {
                "type": answer.get("type"),
                "choice": answer.get("choice"),
                "confidence": answer.get("confidence"),
                "probabilities": answer.get("probabilities"),
            }
        response = {
            "model": raw.get("model", self.model),
            "answers": answers,
            "usage": raw.get("usage", {}),
        }
        for name, question in questions.items():
            read_choice(response, name, question["criteria"])
        record = {
            "response": response,
            "elapsed_seconds": time.perf_counter() - started,
            "attempts": meta.get("attempts", 1),
            "estimated_usd": decisions_estimated_usd(response["usage"]),
        }
        write_json(directory / "response.json", record)
        return record
