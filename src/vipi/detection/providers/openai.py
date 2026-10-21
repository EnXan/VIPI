"""Decisions API predicate checks for text, images and combined evidence."""

import base64
import json

from vipi.config import api_key
from ..policy import INSTRUCTIONS, QUESTION_ID
from ..verdict import probability
from .http import post_json


class Decisions:
    name = "openai"
    model = "gpt-6-luna"
    identity = model
    native = False

    def __init__(self, *, transport=post_json):
        self.key = api_key("OPENAI_API_KEY")
        self.transport = transport

    def check(self, state, image=None):
        if not self.key:
            raise ValueError("Set OPENAI_API_KEY for Decisions.")
        text = json.dumps(state, ensure_ascii=False, sort_keys=True)
        content = [{"type": "input_text", "text": text}]
        if image:
            content.append(
                {
                    "type": "input_image",
                    "image_url": "data:image/png;base64,"
                    + base64.b64encode(image).decode("ascii"),
                }
            )
        raw, meta = self.transport(
            "https://api.openai.com/v1/decisions",
            self.key,
            {
                "model": self.model,
                "input": [{"role": "user", "content": content}],
                "questions": [
                    {
                        "type": "predicate",
                        "name": QUESTION_ID,
                        "instructions": INSTRUCTIONS,
                    }
                ],
            },
        )
        answer = next(
            (x for x in raw.get("answers", []) if x.get("name") == QUESTION_ID), {}
        )
        if answer.get("type") != "predicate":
            return {
                "status": "refused" if answer.get("type") == "refusal" else "error",
                "error": "Decisions refused or omitted the predicate answer.",
                "raw": raw,
                **meta,
            }
        tokens = raw.get("usage", {}).get("input_tokens")
        try:
            score = probability(answer.get("probability"))
        except ValueError as error:
            return {"status": "error", "error": str(error), "raw": raw, **meta}
        return {
            "status": "completed",
            "probability": score,
            "question_id": QUESTION_ID,
            "model": raw.get("model", self.model),
            "input_tokens": tokens,
            "estimated_usd": tokens * 0.10 / 1_000_000
            if isinstance(tokens, int) and tokens >= 0
            else None,
            "confidence": None,
            "raw": raw,
            **meta,
        }
