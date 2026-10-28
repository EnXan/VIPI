"""Dated API list-rate estimates, separate from provider invoices and local compute."""

from statistics import mean, median
import math
from vipi.config import GOOGLE_OCR_MODEL as GOOGLE_MODEL, LUNA_OCR_MODEL as LUNA_MODEL

PRICING_DATE = "2026-10-25"
API_MODELS = (LUNA_MODEL, GOOGLE_MODEL, "mistral-ocr-4-1")


def cost_for_result(result):
    model = result["model"]
    if model not in API_MODELS:
        return {
            "currency": "USD",
            "estimated_usd": 0.0,
            "kind": "local_api_fee",
            "note": "No OCR API fee; local electricity and hardware costs are not measured.",
            "usage": {},
        }
    estimates, usage = [], []
    for step in result.get("variants", []):
        prep = step.get("preprocessing", {})
        value = prep.get("usage") or prep.get("usage_info") or {}
        usage.append(value)
        if model == LUNA_MODEL:
            incoming, outgoing = value.get("input_tokens"), value.get("output_tokens")
            cached = (value.get("input_tokens_details") or {}).get("cached_tokens", 0)
            if not all(
                isinstance(v, (int, float)) for v in (incoming, outgoing, cached)
            ):
                estimates.append(None)
                continue
            long_context = incoming > 272_000
            estimates.append(
                (
                    max(0, incoming - cached) * (0.20 if long_context else 0.10)
                    + cached * (0.02 if long_context else 0.01)
                    + outgoing * (0.75 if long_context else 0.50)
                )
                / 1_000_000
            )
        elif model == GOOGLE_MODEL:
            units = value.get("units")
            estimates.append(
                units * 1.50 / 1000 if isinstance(units, (int, float)) else None
            )
        else:
            pages = value.get("pages_processed")
            estimates.append(
                pages * 4.0 / 1000 if isinstance(pages, (int, float)) else None
            )
    sources = {
        LUNA_MODEL: "https://developers.openai.com/api/docs/models/gpt-6-luna",
        GOOGLE_MODEL: "https://cloud.google.com/vision/pricing",
        "mistral-ocr-4-1": "https://docs.mistral.ai/models/ocr-4-1",
    }
    rates = {
        LUNA_MODEL: {
            "input_per_million": 0.10,
            "cached_input_per_million": 0.01,
            "output_per_million": 0.50,
            "long_context_threshold": 272_000,
        },
        GOOGLE_MODEL: {"per_1000_units": 1.50},
        "mistral-ocr-4-1": {"per_1000_pages": 4.0},
    }
    known = bool(estimates) and all(value is not None for value in estimates)
    amount = sum(estimates) if known else None
    return {
        "currency": "USD",
        "kind": "list_rate_estimate",
        "estimated_usd": amount,
        "usage": usage,
        "rates": rates[model],
        "pricing_checked_at": PRICING_DATE,
        "source": sources[model],
        "range_usd": [0, amount] if model == GOOGLE_MODEL and known else None,
        "note": (
            "List-rate estimate before account discounts, free allowances and taxes; not an invoice. "
            + (
                "Google monthly free quota and volume tier are unknown. "
                if model == GOOGLE_MODEL
                else ""
            )
            + (
                "Standard global rates; regional premiums and unreported cache-write fees are excluded."
                if model == LUNA_MODEL
                else ""
            )
        ).strip(),
    }


def performance_summary(items):
    done = [
        item
        for item in items
        if item["state"] in {"completed", "failed"}
        or (item["state"] == "cancelled" and item.get("run_id"))
    ]
    times = sorted(
        item["elapsed_seconds"]
        for item in done
        if isinstance(item.get("elapsed_seconds"), (int, float))
    )
    costs = [item.get("cost") or {} for item in done]
    amounts = [
        cost["estimated_usd"]
        for cost in costs
        if isinstance(cost.get("estimated_usd"), (int, float))
    ]
    unknown = len(done) - len(amounts)
    subtotal = sum(amounts)
    complete = subtotal if done and not unknown else None
    valid = sum(item.get("valid") is True for item in done)
    return {
        "measured_images": len(times),
        "total_seconds": sum(times),
        "mean_seconds": mean(times) if times else None,
        "median_seconds": median(times) if times else None,
        "initialization_seconds": sum(
            item.get("initialization_seconds", 0) for item in done
        ),
        "inference_seconds": sum(item.get("inference_seconds", 0) for item in done),
        "p95_seconds": times[max(0, math.ceil(len(times) * 0.95) - 1)]
        if times
        else None,
        "known_estimated_api_cost_usd": subtotal,
        "estimated_api_cost_usd": complete,
        "cost_unknown_images": unknown,
        "estimated_api_cost_per_image_usd": complete / len(done)
        if complete is not None
        else None,
        "estimated_api_cost_per_pass_usd": complete / valid
        if complete is not None and valid
        else None,
    }
