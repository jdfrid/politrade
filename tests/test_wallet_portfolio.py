"""Tests for Polymarket portfolio parsing."""

from politrade.web.wallet_portfolio import build_portfolio_summary, parse_portfolio_position


def test_parse_position_brazil():
    raw = {
        "title": "Will Brazil win on 2026-06-29?",
        "outcome": "Yes",
        "size": 17.2,
        "avgPrice": 0.58,
        "curPrice": 0.575,
        "initialValue": 10.0,
        "currentValue": 9.91,
        "cashPnl": -0.08,
        "percentPnl": -0.84,
    }
    pos = parse_portfolio_position(raw)
    assert pos is not None
    assert pos.traded_usd == 10.0
    assert pos.to_win_usd == 17.2
    assert pos.avg_cents == 58.0 if hasattr(pos, "avg_cents") else round(pos.avg_price * 100, 1) == 58.0


def test_build_portfolio_summary():
    raw = [{
        "title": "Test market",
        "outcome": "No",
        "size": 1.7,
        "avgPrice": 0.58,
        "curPrice": 0.58,
        "initialValue": 1.0,
        "currentValue": 1.0,
        "cashPnl": 0.0,
        "percentPnl": 0.0,
    }]
    s = build_portfolio_summary(raw, cash_usd=9.18)
    assert s["cash_usd"] == 9.18
    assert s["positions_value_usd"] == 1.0
    assert s["total_value_usd"] == 10.18
    assert len(s["positions"]) == 1

    s2 = build_portfolio_summary(raw, cash_usd=None, value_api=1.0)
    assert s2["cash_usd"] is None
    assert s2["total_value_usd"] == 1.0
