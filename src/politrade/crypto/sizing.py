"""Recommended bet sizing for simulation and live."""

from __future__ import annotations

from typing import Any

from politrade.crypto.strategy import DecisionAction, StrategyDecision


def recommend_bet_usd(
    decision: StrategyDecision,
    virtual_balance: float,
    cfg: dict[str, Any],
) -> float:
    if decision.action != DecisionAction.BET:
        return 0.0
    if virtual_balance < 1.0:
        return 0.0

    base = float(cfg.get("bet_usd", 5))
    edge = decision.edge_pct or float(cfg.get("min_edge_pct", 15))
    conf = decision.confidence or 50.0
    min_edge = float(cfg.get("min_edge_pct", 15))

    edge_boost = max(0.0, (edge - min_edge) / 40.0)
    conf_boost = conf / 200.0
    multiplier = min(2.0, 1.0 + edge_boost + conf_boost)
    amount = base * multiplier

    max_bet = float(cfg.get("max_bet_usd", cfg.get("max_position_usd", 50)))
    cap_pct = float(cfg.get("max_bet_pct_balance", 0.10))
    amount = min(amount, max_bet, virtual_balance * cap_pct)
    return max(1.0, round(amount, 2))


def entry_timing_label(
    phase: str,
    seconds_elapsed: int,
    cfg: dict[str, Any],
) -> str:
    first = int(cfg.get("no_bet_first_seconds", 120))
    last = int(cfg.get("no_bet_last_seconds", 60))
    window = 300

    if phase == "early":
        wait = max(0, first - seconds_elapsed)
        minute = seconds_elapsed // 60 + 1
        return f"המתן {wait}s (דקה {minute}) — גרסה מגדירה כניסה מ-{first}s"
    if phase == "bet":
        remaining = max(0, window - last - seconds_elapsed)
        bucket = "דקה 1" if seconds_elapsed < 60 else ("דקה 2" if seconds_elapsed < 120 else "דקה 3+")
        return f"{bucket} — חלון פתוח ({remaining}s נותרו)"
    if phase == "late":
        return "מאוחר — חלון ההימור נסגר"
    if phase == "closed":
        return "נסגר"
    return "—"


def worth_investing(decision: StrategyDecision) -> bool:
    return decision.action == DecisionAction.BET
