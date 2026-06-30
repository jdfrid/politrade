"""Tests for strategy parameter space."""

from politrade.crypto.strategy_space import (
    StrategyParams,
    initial_population,
    mutate_params,
    random_params,
)


def test_initial_population_unique_hashes():
    pop = initial_population(12)
    hashes = [p.param_hash() for p in pop]
    assert len(pop) == 12
    assert len(set(hashes)) == 12


def test_mutate_changes_something():
    base = StrategyParams(
        strategy_mode="follow_oracle",
        min_edge_pct=15,
        bet_usd=5,
    )
    changed = False
    for _ in range(20):
        m = mutate_params(base)
        if m.to_cfg() != base.to_cfg():
            changed = True
            break
    assert changed


def test_random_params_valid_mode():
    p = random_params()
    assert p.strategy_mode in (
        "follow_oracle", "contrarian", "best_edge", "always_up", "always_down",
    )
    assert p.label()
