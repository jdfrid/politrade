"""Tests for parallel sim optimizer."""

import json

from politrade.crypto.sim_optimizer import ensure_population, evolve_after_cycle, variant_to_dict
from politrade.crypto.strategy_space import StrategyParams
from politrade.storage.repository import Repository


def test_ensure_population_seeds_variants(tmp_path, monkeypatch):
    db = tmp_path / "opt.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db}")
    repo = Repository()
    count = ensure_population(repo, start_balance=500.0)
    assert count >= 20
    assert repo.is_variants_seeded()
    champion = repo.get_champion_variant()
    assert champion is not None
    assert champion.balance == 500.0


def test_evolve_after_cycle_sets_champion(tmp_path, monkeypatch):
    db = tmp_path / "opt2.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db}")
    repo = Repository()
    ensure_population(repo)

    variants = repo.list_active_variants()
    for v in variants[:3]:
        repo.record_variant_cycle_stats(v.id, cycle_pnl=10.0, wins=2, losses=0, bets=2)
    for v in variants[3:6]:
        repo.record_variant_cycle_stats(v.id, cycle_pnl=-5.0, wins=0, losses=2, bets=2)

    result = evolve_after_cycle(1000, repo)
    assert result["champion_id"]
    champion = repo.get_champion_variant()
    assert champion and champion.is_champion
    assert variant_to_dict(champion)["cumulative_pnl"] >= 0


def test_variant_params_roundtrip(tmp_path, monkeypatch):
    db = tmp_path / "opt3.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db}")
    repo = Repository()
    params = StrategyParams(strategy_mode="contrarian", min_edge_pct=0, bet_usd=8)
    v = repo.create_sim_variant(
        label=params.label(),
        params_json=json.dumps(params.to_cfg()),
        param_hash=params.param_hash(),
        start_balance=1000,
    )
    d = variant_to_dict(v)
    assert d["params"]["strategy_mode"] == "contrarian"
    assert d["params"]["bet_usd"] == 8
