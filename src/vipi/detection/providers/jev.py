"""Direct TypeSafe System One API (Noul is a scalar, not confidence)."""

import base64

from vipi.config import api_key, JEV_MODEL
from ..policy import INSTRUCTIONS, QUESTION_ID, state as policy_state
from ..verdict import probability
from .http import post_json


class Jev:
    name = "jev"
    model = JEV_MODEL
    identity = model

    def __init__(self, *, transport=post_json):
        self.key = api_key("TYPESAFE_API_KEY", "JEV_API_KEY")
        self.transport = transport

    def check(self, state):
        return self._check(state)

    def check_image(self, image):
        from vipi.images import decision_preview, png_bytes

        reference = "<image>"
        submitted = decision_preview(image)
        result = self._check(
            policy_state({"image": reference}),
            assets={
                reference: {
                    "type": "image",
                    "format": "png",
                    "data_base64": base64.b64encode(png_bytes(submitted)).decode(
                        "ascii"
                    ),
                }
            },
        )
        return {**result, "submitted_image_size": list(submitted.size)}

    def _check(self, evidence_state, *, assets=None):
        if not self.key:
            raise ValueError("Set TYPESAFE_API_KEY for Jev.")
        payload = {
            "model": self.model,
            "state": evidence_state,
            "questions": {QUESTION_ID: {"type": "noul", "instructions": INSTRUCTIONS}},
        }
        transport_options = {}
        if assets is not None:
            payload["assets"] = assets
            transport_options["headers"] = {"TypeSafe-Danger-Zone-Images": "true"}
        raw, meta = self.transport(
            "https://api.typesafe.ai/v1/systemone",
            self.key,
            payload,
            **transport_options,
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
