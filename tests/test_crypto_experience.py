"""Tests for sim+live experience learning."""

from politrade.config import AppConfig
from politrade.crypto.experience import (
    apply_experience_to_decision,
    build_experience,
    refresh_experience,
)
from politrade.crypto.strategy import DecisionAction, StrategyDecision
from politrade.crypto.window import BetSide, CryptoAsset, CryptoWindow
from politrade.storage.repository import Repository


def test_build_experience_merges_sim_and_live(monkeypatch, tmp_path):
    db_path = tmp_path / "exp.db"
    config = AppConfig()
    monkeypatch.setattr(config.env, "database_url", f"sqlite:///{db_path}")
    repo = Repository(config)

    for i, won in enumerate((True, True, False, True, True, False, True, True)):
        repo.create_sim_bet(
            asset="btc",
            window_ts=1_700_000_000 + i * 300,
            slug=f"btc-{i}",
            side="up",
            token_id="t",
            open_oracle_price=50000.0,
            entry_price=0.5,
            bet_usd=5,
            shares=10,
            edge_pct=15.0,
            decision_reason="test",
            seconds_at_entry=30 + i,
        )
        bets = repo.get_sim_bets_for_window(1_700_000_000 + i * 300)
        repo.resolve_sim_bet(bets[0].id, won=won, oracle_close_price=50100.0, realized_pnl=5 if won else -5)

    exp = build_experience(repo)
    assert exp["total_resolved"] == 8
    assert "btc" in exp["by_asset"]
    assert exp["by_asset"]["btc"]["count"] == 8


def test_apply_experience_tightens_weak_asset(monkeypatch, tmp_path):
    db_path = tmp_path / "exp2.db"
    config = AppConfig()
    monkeypatch.setattr(config.env, "database_url", f"sqlite:///{db_path}")
    repo = Repository(config)

    for i in range(10):
        repo.create_sim_bet(
            asset="eth",
            window_ts=1_700_000_100 + i * 300,
            slug=f"eth-{i}",
            side="up",
            token_id="t",
            open_oracle_price=3000.0,
            entry_price=0.5,
            bet_usd=5,
            shares=10,
            edge_pct=16.0,
            decision_reason="test",
            seconds_at_entry=40,
        )
        bet = repo.get_sim_bets_for_window(1_700_000_100 + i * 300)[0]
        repo.resolve_sim_bet(bet.id, won=(i < 3), oracle_close_price=3001.0, realized_pnl=5 if i < 3 else -5)

    exp = refresh_experience(repo)
    decision = StrategyDecision(
        action=DecisionAction.BET,
        side=BetSide.UP,
        token_id="t",
        entry_ask=0.5,
        edge_pct=16.0,
        seconds_elapsed=40,
    )
    eth_window = CryptoWindow(
        asset=CryptoAsset.ETH,
        window_ts=1,
        slug="e",
        up_token_id="u",
        down_token_id="d",
    )
    out = apply_experience_to_decision(decision, eth_window, base_min_edge=15, experience=exp)
    assert out.action == DecisionAction.SKIP
