"""Tests for simulation statistics."""

from politrade.crypto.sim_stats import build_sim_stats
from politrade.storage.repository import Repository


def test_build_sim_stats_empty(tmp_path, monkeypatch):
    db = tmp_path / "stats.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db}")
    repo = Repository()
    repo.reset_sim_ledger(1000)
    stats = build_sim_stats(repo)
    assert stats["champion"]["wins"] == 0
    assert stats["champion"]["total_invested_usd"] == 0
    assert stats["timeline"] == []


def test_build_sim_stats_with_bets(tmp_path, monkeypatch):
    db = tmp_path / "stats2.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db}")
    repo = Repository()
    repo.reset_sim_ledger(1000)
    b1 = repo.create_sim_bet(
        asset="btc",
        window_ts=1000,
        slug="btc-updown-5m-1000",
        side="up",
        token_id="up",
        open_oracle_price=100.0,
        entry_price=0.5,
        bet_usd=10,
        shares=20,
    )
    b2 = repo.create_sim_bet(
        asset="eth",
        window_ts=1000,
        slug="eth-updown-5m-1000",
        side="down",
        token_id="down",
        open_oracle_price=200.0,
        entry_price=0.6,
        bet_usd=5,
        shares=8.33,
    )
    repo.resolve_sim_bet(b2.id, won=True, oracle_close_price=100.0, realized_pnl=3.0)

    repo.create_sim_cycle(
        window_ts=1000,
        cycle_pnl=3.0,
        cumulative_pnl=3.0,
        wins=1,
        losses=0,
        bets_taken=2,
    )

    stats = build_sim_stats(repo)
    assert stats["champion"]["wins"] == 1
    assert stats["champion"]["open"] == 1
    assert stats["champion"]["total_invested_usd"] == 15.0
    assert stats["champion"]["total_pnl_usd"] == 3.0
    assert stats["champion"]["win_rate_pct"] == 100.0
    assert len(stats["timeline"]) == 1
    assert stats["by_asset"]
