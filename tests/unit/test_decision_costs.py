"""Price cache reads/writes once, with unknown usage kept explicit."""

import pytest

from vipi.ocr.costs import decisions_estimated_usd


def test_default_decisions_cache_write_is_a_total_rate_not_an_extra_input_charge():
    usage = {
        "input_tokens": 100_000,
        "input_tokens_details": {
            "cached_tokens": 0,
            "cache_write_tokens": 100_000,
        },
        "output_tokens": 10_000,
    }
    assert decisions_estimated_usd(usage) == 0.0125


def test_short_context_decisions_cache_rates():
    usage = {
        "input_tokens": 100_000,
        "input_tokens_details": {"cached_tokens": 20_000, "cache_write_tokens": 30_000},
    }
    assert decisions_estimated_usd(usage) == pytest.approx(0.005 + 0.0002 + 0.00375)
    assert decisions_estimated_usd({"input_tokens": 100_000}) == 0.01


@pytest.mark.parametrize(
    "usage",
    [
        {},
        {"input_tokens": True},
        {"input_tokens": -1},
        {"input_tokens": 10, "input_tokens_details": {"cached_tokens": 11}},
        {
            "input_tokens": 10,
            "input_tokens_details": {"cached_tokens": 6, "cache_write_tokens": 5},
        },
    ],
)
def test_invalid_or_missing_decisions_usage_is_not_priced_as_free(usage):
    assert decisions_estimated_usd(usage) is None
