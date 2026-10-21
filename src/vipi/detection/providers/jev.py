"""Direct TypeSafe System One API (Noul is a scalar, not confidence)."""

from vipi.config import api_key
from ..policy import INSTRUCTIONS, QUESTION_ID
from ..verdict import probability
from .http import post_json


class Jev:
    name = "jev"
    model = "jev-1.13.0"
    identity = model
    native = False

    def __init__(self, *, transport=post_json):
        self.key = api_key("TYPESAFE_API_KEY", "JEV_API_KEY")
        self.transport = transport

    def check(self, state, image=None):
        if not self.key:
            raise ValueError("Set TYPESAFE_API_KEY for Jev.")
        raw, meta = self.transport(
            "https://api.typesafe.ai/v1/systemone",
            self.key,
            {
                "model": self.model,
                "state": state,
                "questions": {
                    QUESTION_ID: {"type": "noul", "instructions": INSTRUCTIONS}
                },
            },
        )
        answer = raw.get("answers", {}).get(QUESTION_ID, {})
        if answer.get("type") != "noul":
            return {
                "status": "error",
                "error": "Missing or invalid Jev Noul answer.",
                "raw": raw,
                **meta,
            }
        tokens = raw.get("usage", {}).get("input_tokens")
        try:
            score = probability(answer.get("noul"))
        except ValueError as error:
            return {"status": "error", "error": str(error), "raw": raw, **meta}
        return {
            "status": "completed",
            "probability": score,
            "question_id": QUESTION_ID,
            "model": raw.get("model", self.model),
            "input_tokens": tokens,
            "estimated_usd": tokens * 0.042 / 1_000_000
            if isinstance(tokens, int) and tokens >= 0
            else None,
            "confidence": None,
            "raw": raw,
            **meta,
        }
