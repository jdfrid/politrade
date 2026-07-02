"""Tests for strategy parameter space."""

from politrade.crypto.strategy_space import (
    StrategyParams,
    initial_population,
    mutate_params,
    population_for_settings,
    random_params,
    user_scenario_grid,
)


def test_initial_population_unique_hashes():
    pop = initial_population(12)
    hashes = [p.param_hash() for p in pop]
    assert len(pop) == 12
    assert len(set(hashes)) == 12


def test_user_scenario_grid_respects_limit():
    settings = {
        "sim_test_edges": "0,10,20",
        "sim_test_bets": "3,5",
        "sim_test_first_seconds": "0,30",
        "sim_test_last_seconds": "0",
        "sim_test_modes": "follow_oracle",
        "crypto_max_entry_price": 0.92,
        "crypto_min_move_pct": 0,
    }
    grid = user_scenario_grid(settings, limit=36)
    assert len(grid) == 12
    assert len({p.param_hash() for p in grid}) == 12


def test_user_scenario_grid_caps_at_limit():
    settings = {
        "sim_test_edges": "0,5,10,15,20",
        "sim_test_bets": "3,5,10",
        "sim_test_first_seconds": "0,15,30,60",
        "sim_test_last_seconds": "0,30",
        "sim_test_modes": "follow_oracle,contrarian",
        "crypto_max_entry_price": 0.92,
        "crypto_min_move_pct": 0,
    }
    grid = user_scenario_grid(settings, limit=36)
    assert len(grid) <= 36
    assert len({p.param_hash() for p in grid}) == len(grid)


def test_population_for_settings_custom():
    settings = {
        "sim_use_custom_scenarios": True,
        "sim_test_edges": "10",
        "sim_test_bets": "5",
        "sim_test_first_seconds": "5",
        "sim_test_last_seconds": "0",
        "sim_test_modes": "follow_oracle",
        "crypto_max_entry_price": 0.92,
        "crypto_min_move_pct": 0,
    }
    pop = population_for_settings(settings, count=36)
    assert len(pop) == 1
    assert pop[0].min_edge_pct == 10
    assert pop[0].no_bet_first_seconds == 5


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
