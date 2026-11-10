"""Dated API list-rate estimates, separate from provider invoices and local compute."""

from vipi.config import GOOGLE_OCR_MODEL as GOOGLE_MODEL, LUNA_OCR_MODEL as LUNA_MODEL
from vipi.config import LOCAL_DECISION_PROVIDERS

PRICING_DATE = "2026-10-25"
API_MODELS = (LUNA_MODEL, GOOGLE_MODEL, "mistral-ocr-4-1")
DECISIONS_PRICING = {
    "checked_at": "2026-11-02",
    "input_per_million": 0.10,
    "cached_input_per_million": 0.01,
    "cache_write_per_million": 0.125,
    "cache_ttl": "30m",
    "scope": "standard global rates; regional and long-context premiums excluded",
    "source": "https://developers.openai.com/api/docs/guides/decisions",
    "cache_source": "https://developers.openai.com/api/docs/guides/prompt-caching",
    "rates_source": "https://developers.openai.com/api/docs/pricing",
}


def decisions_estimated_usd(usage):
    """Price default global Decisions usage, including 30-minute cache writes.

    Read/write counts are subsets of input_tokens. Output is uncharged. These
    list rates exclude discounts, regional/long-context premiums and unknown retries.
    """
    incoming = usage.get("input_tokens")
    details = usage.get("input_tokens_details") or {}
    cached = details.get("cached_tokens", 0)
    written = details.get("cache_write_tokens", 0)
    if (
        any(
            type(value) is not int or value < 0 for value in (incoming, cached, written)
        )
        or cached + written > incoming
    ):
        return None
    rates = DECISIONS_PRICING
    return (
        (incoming - cached - written) * rates["input_per_million"]
        + cached * rates["cached_input_per_million"]
        + written * rates["cache_write_per_million"]
    ) / 1_000_000


def cost_for_result(result):
    """Estimate saved OCR and visual-decision API charges for one run."""
    selection = result.get("selection")
    if selection:
        decisions = []
        for decision in selection["decisions"]:
            decisions.extend(decision.get("records", [decision]))
        estimates = [decision.get("estimated_usd") for decision in decisions]
        provider = selection.get("provider")
        estimate = (
            sum(estimates)
            if all(isinstance(value, (int, float)) for value in estimates)
            else None
        )
        ocr = _ocr_cost_for_result(result)
        total = (
            estimate + ocr["estimated_usd"]
            if estimate is not None and ocr["estimated_usd"] is not None
            else None
        )
        cloud = provider in {"openai-decisions", "jev"}
        return {
            "currency": "USD",
            "estimated_usd": total,
            "selection_estimated_usd": estimate,
            "selection_api_calls": len(decisions) if cloud else 0,
            "selection_http_attempts": sum(d.get("attempts", 1) for d in decisions)
            if cloud
            else 0,
            "ocr_api_calls": len(result.get("variants", []))
            if result["model"] in API_MODELS
            else 0,
            "kind": "ocr_and_visual_selection",
            "ocr": ocr,
            "usage": [d["response"].get("usage") for d in decisions],
            "note": (
                "Sum of saved Decisions fee estimates; not an invoice."
                if provider == "openai-decisions"
                else "No external decision API fee; local compute is not measured."
                if provider in LOCAL_DECISION_PROVIDERS
                else "Jev usage is recorded. Total API cost is unknown because no verified Jev rate is configured."
            ),
        }
    return _ocr_cost_for_result(result)


def _ocr_cost_for_result(result):
    """Estimate OCR fees from each recorded provider usage entry."""
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
