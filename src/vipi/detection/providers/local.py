"""Fully local injection decisions with the same policy as hosted providers."""

from vipi.local_decisions import LocalDecisionModel
from ..policy import INSTRUCTIONS, QUESTION_ID
from ..verdict import probability


class LocalDecisionProvider:

    def __init__(self, name, directory, *, runtime=None):
        self.name = name
        self.runtime = runtime or LocalDecisionModel(name, directory)
        self.model = self.runtime.model
        self.identity = self.runtime.identity

    def check(self, state):
        response = self.runtime.ask(
            state, {QUESTION_ID: {"type": "noul", "instructions": INSTRUCTIONS}}
        )
        answer = response.get("answers", {}).get(QUESTION_ID, {})
        if answer.get("type") != "noul":
            raise ValueError("Local decision model omitted the injection predicate.")
        return {
            "status": "completed",
            "probability": probability(answer.get("noul")),
            "question_id": QUESTION_ID,
            "model": self.model,
            "input_tokens": response.get("usage", {}).get("input_tokens"),
            "estimated_usd": 0.0,
            "attempts": 1,
            "cost_uncertain": False,
            "cost_scope": "API fees only; excludes local compute",
            "raw": response,
        }
