"""Tests for portfolio trading helpers."""

from politrade.web.portfolio_trade import market_outcomes, normalize_market_slug


def test_normalize_market_slug_url():
    url = "https://polymarket.com/event/fifwc-bra-jpn-2026-06-29/fifwc-bra-jpn-2026-06-29-bra"
    assert normalize_market_slug(url) == "fifwc-bra-jpn-2026-06-29-bra"


def test_normalize_market_slug_plain():
    assert normalize_market_slug("btc-updown-5m-1000") == "btc-updown-5m-1000"


def test_market_outcomes_parses_json_strings():
    market = {
        "clobTokenIds": '["111", "222"]',
        "outcomes": '["Yes", "No"]',
    }
    out = market_outcomes(market)
    assert len(out) == 2
    assert out[0]["outcome"] == "Yes"
    assert out[0]["token_id"] == "111"
    assert out[1]["token_id"] == "222"
