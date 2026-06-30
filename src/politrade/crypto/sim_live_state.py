"""Build live simulation dashboard payload."""

from __future__ import annotations

import time
from typing import Any

from politrade.config import AppConfig
from politrade.crypto.cycle_summary import cycle_to_dict
from politrade.crypto.sim_mode import (
    can_enable_live,
    get_readiness_score,
    get_trading_mode,
    is_auto_learn_enabled,
    is_live_enabled,
)
from politrade.crypto.sim_runner import get_sim_runner
from politrade.crypto.strategy import crypto_cfg
from politrade.crypto.gamma_discovery import discover_5m_windows_from_gamma
from politrade.crypto.window import compute_window_ts, WINDOW_SECONDS
from politrade.storage.repository import Repository


def build_sim_live(config: AppConfig | None = None) -> dict[str, Any]:
    from politrade.web.user_settings import get_effective_config

    cfg = config or get_effective_config()
    repo = Repository(cfg)
    runner = get_sim_runner()
    state = runner.get_live_state()
    now_wts = compute_window_ts()

    balance = repo.get_sim_balance()
    cumulative = repo.get_sim_cumulative_pnl()
    summary = repo.sim_bets_summary()

    open_bets = []
    for b in repo.get_open_sim_bets():
        open_bets.append({
            "id": b.id,
            "asset": b.asset.upper(),
            "slug": b.slug,
            "side": b.side,
            "bet_usd": b.bet_usd,
            "status": b.status,
        })

    latest_cycle = repo.list_sim_cycles(limit=1)
    prev_cycle = repo.list_sim_cycles(limit=2)
    prev = prev_cycle[1] if len(prev_cycle) > 1 else None

    can_live, live_reason = can_enable_live(repo)

    return {
        "runner": runner.status,
        "state": state,
        "window_ts": now_wts,
        "seconds_remaining": max(0, now_wts + WINDOW_SECONDS - int(time.time())),
        "sim_balance": balance,
        "sim_start_balance": repo.get_sim_start_balance(),
        "cumulative_pnl": cumulative,
        "summary": summary,
        "open_bets": open_bets,
        "readiness_score": get_readiness_score(repo),
        "trading_mode": get_trading_mode(repo),
        "live_enabled": is_live_enabled(repo),
        "can_enable_live": can_live,
        "live_reason": live_reason,
        "auto_learn": is_auto_learn_enabled(repo),
        "latest_cycle": cycle_to_dict(latest_cycle[0]) if latest_cycle else None,
        "prev_cycle_pnl_delta": prev.cycle_pnl if prev else None,
        "settings": {
            k: crypto_cfg(cfg).get(k)
            for k in (
                "bet_usd", "min_edge_pct", "max_entry_price", "min_move_pct",
                "no_bet_first_seconds", "no_bet_last_seconds",
            )
        },
        "markets_count": len(discover_5m_windows_from_gamma(cfg)),
    }


def build_sim_cycles(config: AppConfig | None = None, *, limit: int = 30) -> dict[str, Any]:
    from politrade.web.user_settings import get_effective_config

    cfg = config or get_effective_config()
    repo = Repository(cfg)
    cycles = [cycle_to_dict(c) for c in repo.list_sim_cycles(limit=limit)]
    lessons = [
        {
            "id": l.id,
            "window_ts": l.window_ts,
            "lessons_he": l.lessons_he,
            "params_before": l.params_before,
            "params_after": l.params_after,
            "created_at": l.created_at.isoformat() if l.created_at else "",
        }
        for l in repo.list_sim_lessons(limit=limit)
    ]
    return {"cycles": cycles, "lessons": lessons}
