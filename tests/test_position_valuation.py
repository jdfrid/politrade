"""Tests for position valuation and exit thresholds."""

from datetime import datetime, timezone

from politrade.execution.position_valuation import (
    ExitTargets,
    check_exit_reason,
    value_position,
)
from politrade.storage.models import Position


def _position(entry_cost: float = 50.0, shares: float = 100.0) -> Position:
    return Position(
        id=1,
        token_id="tok",
        market_id="mkt",
        leader_address="0xabc",
        entry_price=0.5,
        entry_cost_usd=entry_cost,
        shares=shares,
        status="open",
        opened_at=datetime.now(timezone.utc),
    )


def test_value_position_pnl_and_progress():
    pos = _position(entry_cost=50.0, shares=100.0)
    targets = ExitTargets(take_profit_pct=100, stop_loss_pct=50, max_hold_days=30)
    val = value_position(pos, price=0.75, targets=targets)
    assert val.current_value_usd == 75.0
    assert val.pnl_usd == 25.0
    assert val.pnl_pct == 50.0
    assert val.progress_to_tp == 50.0
    assert val.take_profit_target_usd == 100.0
    assert val.stop_loss_target_usd == 25.0


def test_exit_targets_from_multiplier_fallback():
    targets = ExitTargets.from_config(
        {"take_profit_multiplier": 2.0, "stop_loss_multiplier": 0.5}
    )
    assert targets.take_profit_pct == 100.0
    assert targets.stop_loss_pct == 50.0


def test_check_exit_take_profit():
    pos = _position()
    targets = ExitTargets(take_profit_pct=100, stop_loss_pct=50, max_hold_days=30)
    val = value_position(pos, price=1.0, targets=targets)
    assert check_exit_reason(pos, val, targets=targets, age_days=0) == "take_profit"


def test_check_exit_stop_loss():
    pos = _position()
    targets = ExitTargets(take_profit_pct=100, stop_loss_pct=50, max_hold_days=30)
    val = value_position(pos, price=0.2, targets=targets)
    assert check_exit_reason(pos, val, targets=targets, age_days=0) == "stop_loss"


def test_check_exit_max_hold():
    pos = _position()
    targets = ExitTargets(take_profit_pct=100, stop_loss_pct=50, max_hold_days=30)
    val = value_position(pos, price=0.5, targets=targets)
    assert check_exit_reason(pos, val, targets=targets, age_days=31) == "max_hold_time"
