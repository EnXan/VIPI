"""Operational comparison only; OCR transcripts do not supply attack labels."""

from statistics import median


def statistics(results, field):
    groups = {}
    for identifier in sorted({x[field] for x in results}):
        rows = [x for x in results if x[field] == identifier]
        live = [x for x in rows if not x.get("replayed")]
        times = sorted(x["latency_seconds"] for x in live)
        costs = [x.get("estimated_usd") for x in live]
        tokens = [x.get("input_tokens") for x in live]
        groups[identifier] = {
            "checks": len(rows),
            "errors": sum(x["status"] != "completed" for x in rows),
            "replayed": len(rows) - len(live),
            "p50_seconds": median(times) if times else None,
            "p95_seconds": times[
                min(len(times) - 1, int((len(times) - 1) * 0.95 + 0.5))
            ]
            if times
            else None,
            "input_tokens": sum(x for x in tokens if x is not None),
            "estimated_usd": sum(x for x in costs if x is not None),
            "cost_incomplete": any(x is None for x in costs)
            or any(x.get("cost_uncertain") for x in live),
        }
    return groups


def comparison(results):
    pairs = {}
    for row in results:
        if row["signal"] in {"jev", "openai", "prompt-guard"}:
            pairs.setdefault(row["reading_id"], {}).setdefault(
                row["provider"], []
            ).append(
                {
                    "check": row["id"],
                    "status": row["status"],
                    "score": row.get("probability"),
                    "verdict": row["verdict"],
                    "start": row.get("start"),
                    "end": row.get("end"),
                    "partial_context": row.get("partial_context", False),
                }
            )
    disagreements = []
    for reading_id, providers in pairs.items():
        verdicts = {}
        for provider, checks in providers.items():
            values = {x["verdict"] for x in checks}
            verdicts[provider] = (
                "flagged"
                if "flagged" in values
                else "not_flagged"
                if values == {"not_flagged"}
                else "unclear"
            )
        if len(set(verdicts.values())) > 1:
            disagreements.append({"reading_id": reading_id, "verdicts": verdicts})
    return {
        "providers": statistics(results, "provider"),
        "signals": statistics(results, "signal"),
        "paired_readings": pairs,
        "disagreements": disagreements,
        "quality_metrics": None,
        "quality_note": "Quality comparison requires separately verified attack labels and benign controls.",
    }
