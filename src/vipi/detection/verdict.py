"""Explicit, versioned thresholds and the binary scan verdict."""

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
    """Binary verdict from completed checks; ``None`` when a required check failed.

    Any completed answer or chunk at or above the threshold detects an
    injection. No answers at all means there was no text to check.
    """
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
        verdict = None
        if limits and any(x >= threshold for x in scores):
            verdict = "injection_detected"
        elif evidence_complete and (
            not answers
            or (limits and len(scores) == len(answers))
        ):
            verdict = "no_injection_detected"
        per_signal[signal] = {
            "verdict": verdict,
            "max_score": max(scores, default=None),
            "checks": len(answers),
            "threshold": threshold,
        }
    verdicts = [x["verdict"] for x in per_signal.values()]
    verdict = (
        "injection_detected"
        if "injection_detected" in verdicts
        else "no_injection_detected"
        if verdicts and all(x == "no_injection_detected" for x in verdicts)
        else None
    )
    scores = [x["max_score"] for x in per_signal.values() if x["max_score"] is not None]
    thresholds_used = [x["threshold"] for x in per_signal.values()]
    return {
        "verdict": verdict,
        "injection_probability": max(scores, default=None),
        "threshold": thresholds_used[0] if len(thresholds_used) == 1 else None,
        "signals": per_signal,
        "threshold_version": thresholds.get("version"),
    }
