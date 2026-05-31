"""Shared position value and exit-threshold calculations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from politrade.storage.models import Position


@dataclass
class ExitTargets:
    take_profit_pct: float
    stop_loss_pct: float
    max_hold_days: int

    @classmethod
    def from_config(cls, exit_cfg: dict[str, Any]) -> ExitTargets:
        tp_pct = exit_cfg.get("take_profit_pct")
        sl_pct = exit_cfg.get("stop_loss_pct")
        if tp_pct is None:
            mult = float(exit_cfg.get("take_profit_multiplier", 2.0))
            tp_pct = (mult - 1.0) * 100.0
        if sl_pct is None:
            mult = float(exit_cfg.get("stop_loss_multiplier", 0.5))
            sl_pct = (1.0 - mult) * 100.0
        return cls(
            take_profit_pct=float(tp_pct),
            stop_loss_pct=float(sl_pct),
            max_hold_days=int(exit_cfg.get("max_hold_days", 30)),
        )


@dataclass
class PositionValuation:
    current_price: float
    current_value_usd: float
    pnl_usd: float
    pnl_pct: float
    progress_to_tp: float
    take_profit_target_usd: float
    stop_loss_target_usd: float


def value_position(
    pos: Position,
    price: float,
    *,
    targets: ExitTargets | None = None,
) -> PositionValuation:
    """Compute live value, PnL, and progress toward take-profit."""
    entry_cost = pos.entry_cost_usd
    current_value = pos.shares * price
    pnl_usd = current_value - entry_cost
    pnl_pct = (pnl_usd / entry_cost * 100.0) if entry_cost > 0 else 0.0

    tp_pct = targets.take_profit_pct if targets else 100.0
    sl_pct = targets.stop_loss_pct if targets else 50.0
    tp_target = entry_cost * (1.0 + tp_pct / 100.0)
    sl_target = entry_cost * (1.0 - sl_pct / 100.0)

    if tp_pct > 0:
        progress = min(100.0, max(0.0, pnl_pct / tp_pct * 100.0))
    else:
        progress = 100.0 if pnl_usd >= 0 else 0.0

    return PositionValuation(
        current_price=price,
        current_value_usd=current_value,
        pnl_usd=pnl_usd,
        pnl_pct=pnl_pct,
        progress_to_tp=progress,
        take_profit_target_usd=tp_target,
        stop_loss_target_usd=sl_target,
    )


def check_exit_reason(
    pos: Position,
    valuation: PositionValuation,
    *,
    targets: ExitTargets,
    age_days: int,
) -> str | None:
    entry_cost = pos.entry_cost_usd
    if valuation.current_value_usd >= valuation.take_profit_target_usd:
        return "take_profit"
    if valuation.current_value_usd <= valuation.stop_loss_target_usd:
        return "stop_loss"
    if age_days > targets.max_hold_days:
        return "max_hold_time"
    if entry_cost <= 0:
        return None
    return None
