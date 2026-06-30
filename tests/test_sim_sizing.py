"""Tests for simulation sizing."""

from politrade.crypto.sizing import entry_timing_label, recommend_bet_usd, worth_investing
from politrade.crypto.strategy import DecisionAction, StrategyDecision


def test_recommend_bet_on_bet_action():
    d = StrategyDecision(
        action=DecisionAction.BET,
        edge_pct=20,
        confidence=60,
    )
    amt = recommend_bet_usd(d, 1000, {"bet_usd": 5, "min_edge_pct": 15})
    assert amt >= 5.0
    assert amt <= 100.0


def test_recommend_zero_on_wait():
    d = StrategyDecision(action=DecisionAction.WAIT, reason="wait")
    assert recommend_bet_usd(d, 1000, {"bet_usd": 5}) == 0.0


def test_entry_timing_bet_phase():
    label = entry_timing_label("bet", 150, {"no_bet_first_seconds": 120, "no_bet_last_seconds": 60})
    assert "עכשיו" in label


def test_worth_investing():
    assert worth_investing(StrategyDecision(action=DecisionAction.BET)) is True
    assert worth_investing(StrategyDecision(action=DecisionAction.SKIP)) is False
