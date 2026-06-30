"""Tests for crypto markets catalog."""

from politrade.crypto.markets_catalog import assess_side_buy, build_progress
from politrade.crypto.window import BetSide, WindowPhase


def test_assess_side_can_buy_when_ready():
    status = assess_side_buy(
        side=BetSide.UP,
        window_closed=False,
        phase=WindowPhase.BET,
        token_id="123",
        ask=0.45,
        trading_ready=True,
        already_bet=False,
        min_bet_usd=5,
        cash_usd=20,
        has_liquidity=True,
    )
    assert status.can_buy is True
    assert status.block_reason == ""


def test_assess_side_blocked_no_clob():
    status = assess_side_buy(
        side=BetSide.DOWN,
        window_closed=False,
        phase=WindowPhase.EARLY,
        token_id="456",
        ask=0.52,
        trading_ready=False,
        already_bet=False,
        min_bet_usd=5,
        cash_usd=None,
        has_liquidity=True,
    )
    assert status.can_buy is False
    assert "CLOB" in status.block_reason


def test_assess_side_blocked_already_bet():
    status = assess_side_buy(
        side=BetSide.UP,
        window_closed=False,
        phase=WindowPhase.BET,
        token_id="123",
        ask=0.40,
        trading_ready=True,
        already_bet=True,
        min_bet_usd=5,
        cash_usd=50,
        has_liquidity=True,
    )
    assert status.can_buy is False
    assert "כבר הימרת" in status.block_reason


def test_build_progress_ready():
    p = build_progress(
        phase=WindowPhase.BET,
        already_bet=False,
        bet_status=None,
        live={
            "decision": {"action": "bet", "side": "up", "edge_pct": 18.5},
            "bet_placed": False,
        },
        auto_bet=True,
    )
    assert p["stage"] == "ready"
    assert "UP" in p["label"]


def test_build_progress_bet_open():
    p = build_progress(
        phase=WindowPhase.BET,
        already_bet=True,
        bet_status="open",
        live=None,
        auto_bet=True,
    )
    assert p["stage"] == "bet_open"
