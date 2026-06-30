"""Tests for structured decision rationale."""

from politrade.crypto.decision_rationale import (
    FactorCategory,
    aggregate_variant_stats,
)
from politrade.crypto.strategy import DecisionAction, StrategyDecision, evaluate_window
from politrade.config import AppConfig
from politrade.crypto.price_feed import OracleSnapshot, TokenPrices
from politrade.crypto.window import CryptoAsset, CryptoWindow


def test_early_wait_has_time_blocker():
    window = CryptoWindow(
        asset=CryptoAsset.BTC,
        window_ts=1000,
        slug="btc-updown-5m-1000",
        up_token_id="up",
        down_token_id="down",
    )
    oracle = OracleSnapshot(CryptoAsset.BTC, 1000, open_price=100.0, current_price=100.1)
    tokens = TokenPrices(up_ask=0.55, down_ask=0.45)
    cfg = {"no_bet_first_seconds": 60, "min_edge_pct": 0, "bet_usd": 5}
    d = evaluate_window(
        window, oracle, tokens, AppConfig(),
        cfg_override=cfg, now=1020,
    )
    assert d.action == DecisionAction.WAIT
    assert d.blocker_category == FactorCategory.TIME.value
    assert "זמן" in d.rationale_he or "מוקדם" in d.rationale_he


def test_bet_includes_profit_and_risk_factors():
    window = CryptoWindow(
        asset=CryptoAsset.BTC,
        window_ts=1000,
        slug="btc-updown-5m-1000",
        up_token_id="up",
        down_token_id="down",
    )
    oracle = OracleSnapshot(CryptoAsset.BTC, 1000, open_price=100.0, current_price=100.2)
    tokens = TokenPrices(up_ask=0.55, down_ask=0.45)
    d = evaluate_window(
        window, oracle, tokens, AppConfig(),
        cfg_override={"no_bet_first_seconds": 0, "min_edge_pct": 0, "bet_usd": 5},
        now=1100,
    )
    assert d.action == DecisionAction.BET
    cats = {f.category if hasattr(f, "category") else f.get("category") for f in d.factors}
    assert FactorCategory.PROFIT.value in cats
    assert FactorCategory.RISK.value in cats


def test_aggregate_variant_stats():
    rows = [
        {"action": "bet", "executed": True, "blocker_category": None},
        {"action": "wait", "executed": False, "blocker_category": "time"},
        {"action": "skip", "executed": False, "blocker_category": "profit"},
    ]
    agg = aggregate_variant_stats(rows)
    assert agg["by_action"]["bet"] == 1
    assert agg["by_blocker"]["time"] == 1
