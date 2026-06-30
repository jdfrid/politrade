"""Rule-based learning between simulation cycles."""

from __future__ import annotations

import json
from typing import Any

from politrade.config import AppConfig
from politrade.crypto.cycle_summary import update_cycle_params_after
from politrade.crypto.sim_mode import is_auto_learn_enabled
from politrade.crypto.strategy import crypto_cfg
from politrade.storage.models import SimCycle
from politrade.storage.repository import Repository
from politrade.web.user_settings import load_user_settings, save_user_settings


def run_learner_after_cycle(
    cycle: SimCycle,
    config: AppConfig | None = None,
    repo: Repository | None = None,
) -> dict[str, Any]:
    from politrade.config import AppConfig

    cfg = config or AppConfig()
    r = repo or Repository(cfg)
    params_before = _crypto_user_params(r)
    params_after = dict(params_before)

    if is_auto_learn_enabled(r):
        recent = r.list_sim_cycles(limit=8)
        params_after = _apply_rules(params_after, recent, r)

    if params_after != params_before:
        save_user_settings(r, {**load_user_settings(r), **params_after})
        r.create_sim_lesson(
            window_ts=cycle.window_ts,
            lessons_he=cycle.lessons_he,
            params_before=json.dumps(params_before, ensure_ascii=False),
            params_after=json.dumps(params_after, ensure_ascii=False),
        )
        update_cycle_params_after(cycle, _params_to_crypto_cfg(params_after), r)

    return {
        "changed": params_after != params_before,
        "params_before": params_before,
        "params_after": params_after,
    }


def _crypto_user_params(repo: Repository) -> dict[str, Any]:
    s = load_user_settings(repo)
    return {
        "crypto_bet_usd": s.get("crypto_bet_usd", 5),
        "crypto_min_edge_pct": s.get("crypto_min_edge_pct", 15),
        "crypto_max_entry_price": s.get("crypto_max_entry_price", 0.87),
        "crypto_min_move_pct": s.get("crypto_min_move_pct", 0.04),
        "crypto_no_bet_first_seconds": s.get("crypto_no_bet_first_seconds", 120),
        "crypto_no_bet_last_seconds": s.get("crypto_no_bet_last_seconds", 60),
    }


def _params_to_crypto_cfg(params: dict[str, Any]) -> dict[str, Any]:
    return {
        "bet_usd": params.get("crypto_bet_usd"),
        "min_edge_pct": params.get("crypto_min_edge_pct"),
        "max_entry_price": params.get("crypto_max_entry_price"),
        "min_move_pct": params.get("crypto_min_move_pct"),
        "no_bet_first_seconds": params.get("crypto_no_bet_first_seconds"),
        "no_bet_last_seconds": params.get("crypto_no_bet_last_seconds"),
    }


def _apply_rules(
    params: dict[str, Any],
    recent_cycles: list[SimCycle],
    repo: Repository,
) -> dict[str, Any]:
    if not recent_cycles:
        return params

    out = dict(params)
    edge_skips = sum(c.bets_skipped for c in recent_cycles[:5])
    total_markets = sum(c.markets_total for c in recent_cycles[:5]) or 1
    skip_ratio = edge_skips / total_markets

    wins = sum(c.wins for c in recent_cycles[:5])
    losses = sum(c.losses for c in recent_cycles[:5])
    resolved = wins + losses

    if skip_ratio > 0.6:
        edge = float(out.get("crypto_min_edge_pct", 15))
        out["crypto_min_edge_pct"] = max(10.0, edge - 1.0)

    if resolved >= 3 and losses / resolved > 0.4:
        move = float(out.get("crypto_min_move_pct", 0.04))
        out["crypto_min_move_pct"] = min(0.20, round(move + 0.01, 3))

    if resolved >= 5 and wins / resolved > 0.65:
        pnl_sum = sum(c.cycle_pnl for c in recent_cycles[:5])
        if pnl_sum > 0:
            pass

    return out
