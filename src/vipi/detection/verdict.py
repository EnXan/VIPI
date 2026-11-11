"""Explicit, versioned thresholds; preserve positives and incomplete evidence."""

import math

from vipi.config import LOCAL_DECISION_PROVIDERS

SIGNALS = {
    "jev",
    "openai",
    "prompt-guard",
    *LOCAL_DECISION_PROVIDERS,
}


def probability(value):
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or not 0 <= value <= 1
    ):
        raise ValueError("Provider returned an invalid probability.")
    return float(value)


def validate_thresholds(value=None):
    if value is None or value == {}:
        return {}
    if (
        not isinstance(value, dict)
        or set(value) != {"version", "signals"}
        or not isinstance(value["version"], str)
        or not value["version"].strip()
    ):
        raise ValueError("Thresholds require a version and signals object.")
    signals = value["signals"]
    if not isinstance(signals, dict) or set(signals) - SIGNALS:
        raise ValueError("Unknown threshold signal.")
    for item in signals.values():
        if not isinstance(item, dict) or set(item) != {"threshold"}:
            raise ValueError("Each signal requires a threshold.")
        probability(item["threshold"])
    return value


def summarize(results, signals, thresholds, *, evidence_complete=True):
    per_signal = {}
    for signal in signals:
        answers = [x for x in results if x["signal"] == signal]
        scores = [
            x["probability"]
            for x in answers
            if x.get("status") == "completed" and x.get("probability") is not None
        ]
        limits = thresholds.get("signals", {}).get(signal)
        threshold = limits["threshold"] if limits else None
        verdict = "unclear"
        if limits and any(x >= threshold for x in scores):
            verdict = "flagged"
        elif (
            limits
            and evidence_complete
            and answers
            and len(scores) == len(answers)
            and not any(x.get("partial_context") for x in answers)
            and all(x < threshold for x in scores)
        ):
            verdict = "not_flagged"
        per_signal[signal] = {
            "verdict": verdict,
            "max_score": max(scores, default=None),
            "checks": len(answers),
        }
    verdicts = [x["verdict"] for x in per_signal.values()]
    verdict = (
        "flagged"
        if "flagged" in verdicts
        else "not_flagged"
        if verdicts and all(x == "not_flagged" for x in verdicts)
        else "unclear"
    )
    return {
        "verdict": verdict,
        "review_required": verdict != "not_flagged",
        "signals": per_signal,
        "threshold_version": thresholds.get("version"),
    }
