"""Tests for simulation learner."""

from politrade.crypto.learner import _apply_rules
from politrade.storage.models import SimCycle


def test_apply_rules_lowers_edge_on_many_skips():
    params = {"crypto_min_edge_pct": 15.0, "crypto_min_move_pct": 0.04}
    cycles = [
        SimCycle(
            id=i, window_ts=i, markets_total=7, bets_skipped=5, bets_taken=0,
            wins=0, losses=0, cycle_pnl=0, cumulative_pnl=0, win_rate=0,
            summary_he="", lessons_he="", readiness_score=0,
        )
        for i in range(5)
    ]
    out = _apply_rules(params, cycles, None)
    assert out["crypto_min_edge_pct"] < 15.0
