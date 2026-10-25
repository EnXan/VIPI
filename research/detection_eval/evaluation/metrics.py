"""Compare scanner verdicts with reviewed labels; retain abstentions and errors."""

from vipi.detection.pipeline import classifier_names


def outcome(expected, verdict, *, error=False):
    if error:
        return "error"
    if verdict not in {"flagged", "not_flagged"}:
        return "unresolved"
    return {
        ("injection", "flagged"): "true_positive",
        ("injection", "not_flagged"): "false_negative",
        ("benign", "flagged"): "false_positive",
        ("benign", "not_flagged"): "true_negative",
    }[expected, verdict]


def evaluate(case, result, *, error=None):
    answers = result.get("answers", []) if result else []
    failed = (
        error
        or ("Detector check failed." if result is None else None)
        or next(
            (
                row.get("error") or "Detector check failed."
                for row in answers
                if row["status"] != "completed"
            ),
            None,
        )
    )
    verdict = result["verdict"] if result else "unclear"
    return {
        "state": "failed" if failed else "completed",
        "error": failed,
        "verdict": verdict,
        "outcome": outcome(case["expected"], verdict, error=bool(failed)),
        "threshold_version": result.get("threshold_version") if result else None,
        "signals": {
            signal: {
                **value,
                "outcome": outcome(
                    case["expected"],
                    value["verdict"],
                    error=any(
                        row["signal"] == signal and row["status"] != "completed"
                        for row in answers
                    ),
                ),
            }
            for signal, value in (result.get("signals", {}) if result else {}).items()
        },
    }


def counts(outcomes):
    values = list(outcomes)
    result = {
        name: values.count(name)
        for name in (
            "true_positive",
            "true_negative",
            "false_positive",
            "false_negative",
            "unresolved",
            "error",
            "pending",
            "cancelled",
        )
    }
    result["total"] = len(values)
    result["correct"] = result["true_positive"] + result["true_negative"]
    result["incorrect"] = result["false_positive"] + result["false_negative"]
    result["decided"] = result["correct"] + result["incorrect"]
    result["completed"] = result["total"] - result["pending"] - result["cancelled"]
    result["accuracy"] = (
        result["correct"] / result["decided"] if result["decided"] else None
    )
    result["decision_rate"] = (
        result["decided"] / result["completed"] if result["completed"] else None
    )
    return result


def summarize(items, options):
    cases = [case for item in items for case in item.get("cases", [])]
    signals = list(classifier_names(options))
    signals += [
        name for name in ("image", "context") if options[f"{name}_check"] != "off"
    ]

    def signal_outcome(case, signal):
        if signal in case.get("signals", {}):
            return case["signals"][signal]["outcome"]
        if case["state"] == "failed":
            return "error"
        if case["state"] == "cancelled":
            return "cancelled"
        if case["state"] == "completed":
            return "unresolved"
        return "pending"

    return {
        "version": 1,
        "overall": counts(case.get("outcome", "pending") for case in cases),
        "signals": {
            signal: counts(signal_outcome(case, signal) for case in cases)
            for signal in signals
        },
    }
