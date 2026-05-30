"""Tests for trade opportunities."""

from datetime import datetime, timedelta, timezone

from politrade.analysis.trade_opportunities import (
    TradeOpportunity,
    _effective_pnl_pct,
    _finalize_positions,
    _finalize_recent_trades,
    _is_high_profit,
)


def test_pnl_label():
    o = TradeOpportunity(
        trade_id="t1",
        leader_address="0x1",
        market_id="m1",
        token_id="tok1",
        title="Test market",
        outcome="Yes",
        side="BUY",
        size_usd=50,
        price=0.6,
        leader_pnl_usd=12.5,
        leader_pnl_pct=25.0,
        traded_at="2026-01-01",
        copyable=True,
    )
    assert o.pnl_label == "+$12.50"


def test_high_profit_filter():
    high = TradeOpportunity(
        trade_id="t1",
        leader_address="0x1",
        market_id="m1",
        token_id="tok1",
        title="T",
        outcome="Yes",
        side="BUY",
        size_usd=100,
        price=0.5,
        leader_pnl_usd=50,
        leader_pnl_pct=55.0,
        traded_at="",
        copyable=True,
        source="positions",
    )
    low = TradeOpportunity(
        trade_id="t2",
        leader_address="0x1",
        market_id="m2",
        token_id="tok2",
        title="T",
        outcome="Yes",
        side="BUY",
        size_usd=100,
        price=0.5,
        leader_pnl_usd=5,
        leader_pnl_pct=10.0,
        traded_at="",
        copyable=True,
        source="positions",
    )
    assert _is_high_profit(high, 40, 0)
    assert not _is_high_profit(low, 40, 0)
    result = _finalize_positions([low, high], limit=5, min_pct=40, min_usd=0, fallback_pct=10)
    assert len(result) == 1
    assert result[0].trade_id == "t1"


def test_finalize_fallback_tier():
    low = TradeOpportunity(
        trade_id="t2",
        leader_address="0x1",
        market_id="m2",
        token_id="tok2",
        title="T",
        outcome="Yes",
        side="BUY",
        size_usd=100,
        price=0.5,
        leader_pnl_usd=15,
        leader_pnl_pct=15.0,
        traded_at="",
        copyable=True,
        source="positions",
    )
    result = _finalize_positions([low], limit=5, min_pct=40, min_usd=0, fallback_pct=10)
    assert len(result) == 1


def test_finalize_recent_trades_no_profit_filter():
    recent = TradeOpportunity(
        trade_id="t3",
        leader_address="0x1",
        market_id="m3",
        token_id="tok3",
        title="Hot market",
        outcome="Yes",
        side="BUY",
        size_usd=200,
        price=0.4,
        leader_pnl_usd=None,
        leader_pnl_pct=None,
        traded_at="2026-05-19 12:00",
        copyable=True,
        source="trades",
    )
    result = _finalize_recent_trades([recent], limit=5)
    assert len(result) == 1
    assert result[0].trade_id == "t3"


def test_effective_pnl_pct_from_usd():
    o = TradeOpportunity(
        trade_id="t",
        leader_address="0x1",
        market_id="m",
        token_id="tok",
        title="T",
        outcome="",
        side="BUY",
        size_usd=100,
        price=0.5,
        leader_pnl_usd=45,
        leader_pnl_pct=None,
        traded_at="",
        copyable=False,
    )
    assert _effective_pnl_pct(o) == 45.0
