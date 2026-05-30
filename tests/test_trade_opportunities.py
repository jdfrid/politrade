"""Tests for trade opportunities."""

from politrade.analysis.trade_opportunities import (
    TradeOpportunity,
    _effective_pnl_pct,
    _finalize_opportunities,
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
    )
    assert _is_high_profit(high, 40, 0)
    assert not _is_high_profit(low, 40, 0)
    result = _finalize_opportunities([low, high], limit=5, min_pct=40, min_usd=0, fallback_pct=10)
    assert len(result.items) == 1
    assert result.items[0].trade_id == "t1"


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
    )
    result = _finalize_opportunities([low], limit=5, min_pct=40, min_usd=0, fallback_pct=10)
    assert result.relaxed is True
    assert result.used_min_pct == 10
    assert len(result.items) == 1


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
