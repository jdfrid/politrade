"""Tests for trade opportunities."""

from politrade.analysis.trade_opportunities import TradeOpportunity


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
