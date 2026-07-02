"""Unified live real-money activity dashboard."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from politrade.config import AppConfig
from politrade.crypto.budget import wallet_cap_usd
from politrade.crypto.experience import load_experience
from politrade.crypto.markets_catalog import build_markets_catalog
from politrade.crypto.runner import get_crypto_runner
from politrade.crypto.sim_display import enrich_crypto_bet_dict
from politrade.crypto.sim_mode import ensure_live_crypto_runner, is_live_enabled
from politrade.crypto.strategy import crypto_cfg_with_experience
from politrade.crypto.window import compute_window_ts, WINDOW_SECONDS
from politrade.storage.repository import Repository


def _action_label_he(action: str | None) -> str:
    mapping = {
        "bet": "השקע",
        "wait": "ממתין",
        "skip": "דילוג",
    }
    return mapping.get((action or "").lower(), action or "—")


def _worth_label(row: dict[str, Any]) -> str:
    if row.get("bet_placed"):
        return "הימור בוצע"
    action = (row.get("action") or "").lower()
    if action == "bet":
        return "כן — מומלץ"
    if action == "wait":
        return "ממתין לתנאים"
    if action == "skip":
        return "לא"
    return "—"


def _opportunity_row(market: dict[str, Any]) -> dict[str, Any]:
    decision = market.get("decision") or {}
    progress = market.get("progress") or {}
    action = decision.get("action")
    return {
        "title": market.get("title") or market.get("slug"),
        "asset": market.get("asset_label") or market.get("asset", "").upper(),
        "slug": market.get("slug"),
        "window_ts": market.get("window_ts"),
        "window_time": market.get("window_time"),
        "seconds_remaining": market.get("seconds_remaining"),
        "phase": market.get("phase"),
        "is_current": bool(market.get("is_current")),
        "action": action,
        "action_he": _action_label_he(action),
        "side": decision.get("side"),
        "edge_pct": decision.get("edge_pct"),
        "oracle_delta_pct": market.get("oracle_delta_pct"),
        "confidence": decision.get("confidence"),
        "reason": decision.get("reason"),
        "rationale_he": decision.get("rationale_he"),
        "worth_he": _worth_label({
            "bet_placed": market.get("already_bet"),
            "action": action,
        }),
        "bet_placed": bool(market.get("already_bet")),
        "bet_status": market.get("bet_status"),
        "progress_label": progress.get("label"),
        "progress_stage": progress.get("stage"),
        "factors": decision.get("factors") or [],
        "up_edge": (market.get("up") or {}).get("edge_pct"),
        "down_edge": (market.get("down") or {}).get("edge_pct"),
    }


def build_live_dashboard(config: AppConfig | None = None) -> dict[str, Any]:
    from politrade.web.user_settings import get_effective_config

    cfg = config or get_effective_config()
    repo = Repository(cfg)
    now_ts = time.time()
    now_wts = compute_window_ts(int(now_ts))

    live_on = is_live_enabled(repo)
    runner_info: dict[str, Any] = {}
    if live_on:
        runner_info = ensure_live_crypto_runner(repo)

    runner = get_crypto_runner()
    runner_status = runner.status
    runner_state = runner.get_live_state()

    settings = crypto_cfg_with_experience(cfg, repo)
    experience = settings.get("_experience") or load_experience(repo)

    catalog = build_markets_catalog(cfg, repo=Repository(cfg))
    opportunities = [_opportunity_row(m) for m in catalog.get("markets", [])]
    opportunities.sort(key=lambda r: (not r["is_current"], r.get("window_ts") or 0, r.get("asset") or ""))

    recent_bets = [enrich_crypto_bet_dict(b) for b in repo.list_crypto_bets(50)]
    open_bets = [b for b in recent_bets if b.get("status") == "open"]
    summary = repo.crypto_bets_summary()

    cap = wallet_cap_usd(settings)
    exposure = repo.total_open_crypto_exposure()
    budget_left = None if cap <= 0 else max(0.0, round(cap - exposure, 2))

    return {
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "updated_ts": now_ts,
        "window_ts": now_wts,
        "seconds_remaining": max(0, now_wts + WINDOW_SECONDS - int(now_ts)),
        "live_enabled": live_on,
        "runner": {
            **runner_status,
            **runner_info,
            "ticks": runner_state.get("ticks", runner_status.get("ticks", 0)),
            "auto_bet": runner_state.get("auto_bet", runner_status.get("auto_bet")),
            "last_error": runner_state.get("last_error") or runner_status.get("last_error"),
        },
        "catalog": {
            "trading_ready": catalog.get("trading_ready"),
            "cash_usd": catalog.get("cash_usd"),
            "buyable_count": catalog.get("buyable_count"),
            "current_count": catalog.get("current_count"),
            "open_count": catalog.get("open_count"),
        },
        "settings": {
            k: settings.get(k)
            for k in (
                "bet_usd", "min_edge_pct", "max_entry_price", "min_move_pct",
                "no_bet_first_seconds", "no_bet_last_seconds", "strategy_mode",
                "max_wallet_usd", "auto_bet",
            )
        },
        "budget": {
            "cap_usd": cap,
            "exposure_usd": round(exposure, 2),
            "remaining_usd": budget_left,
        },
        "experience": {
            "lesson_he": experience.get("lesson_he"),
            "total_resolved": experience.get("total_resolved", 0),
            "by_asset": experience.get("by_asset", {}),
        },
        "summary": summary,
        "opportunities": opportunities,
        "open_bets": open_bets,
        "recent_bets": recent_bets,
    }
