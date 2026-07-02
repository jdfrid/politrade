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


def _execution_blocker(
    *,
    live_on: bool,
    runner_running: bool,
    auto_bet: bool,
    trading_ready: bool,
    kill_switch: bool,
    decision_action: str | None,
    bet_placed: bool,
) -> str | None:
    if bet_placed:
        return None
    if (decision_action or "").lower() != "bet":
        return None
    if not live_on:
        return "לייב כבוי — לא מבצע הזמנות"
    if kill_switch:
        return "Kill switch פעיל"
    if not runner_running:
        return "Runner לא רץ — לא מבצע הזמנות"
    if not auto_bet:
        return "הימורים אוטומטיים כבויים בהגדרות"
    if not trading_ready:
        return "CLOB לא מוכן — לא נשלחת הזמנה"
    return "ממתין ל-tick הבא של הבוט"


def _build_diagnostics(
    *,
    live_on: bool,
    runner: dict[str, Any],
    settings: dict[str, Any],
    catalog: dict[str, Any],
    kill_switch: bool,
    opportunities: list[dict[str, Any]],
    repo: Repository,
) -> dict[str, Any]:
    issues: list[dict[str, str]] = []
    checks: list[dict[str, str]] = []

    auto_bet = bool(settings.get("auto_bet", True))
    running = bool(runner.get("running"))
    trading_ready = bool(catalog.get("trading_ready"))
    ticks = int(runner.get("ticks") or 0)

    if not live_on:
        issues.append({"level": "err", "text": "מסחר אמיתי כבוי — לחץ «הפעל מסחר אמיתי» בהגדרות"})
    else:
        checks.append({"level": "ok", "text": "מסחר אמיתי מופעל"})

    if not running:
        issues.append({"level": "err", "text": "Crypto runner לא פעיל — רענן את הדף או הפעל מחדש לייב"})
    else:
        checks.append({"level": "ok", "text": f"Runner פעיל · {ticks} ticks"})

    if not auto_bet:
        issues.append({
            "level": "err",
            "text": "«סימולציה אוטומטית» כבוי בהגדרות — הבוט לא שולח הזמנות לייב",
        })
    else:
        checks.append({"level": "ok", "text": "הימורים אוטומטיים פעילים"})

    if kill_switch:
        issues.append({"level": "err", "text": "Kill switch פעיל — כל ההימורים חסומים"})
    else:
        checks.append({"level": "ok", "text": "Kill switch כבוי"})

    if not trading_ready:
        issues.append({"level": "err", "text": "CLOB לא מוכן — בדוק PRIVATE_KEY, FUNDER_ADDRESS ויתרת Cash בארנק"})
    else:
        checks.append({"level": "ok", "text": "CLOB מחובר ומוכן למסחר"})

    current = [o for o in opportunities if o.get("is_current")]
    bet_recs = [o for o in current if (o.get("action") or "").lower() == "bet" and not o.get("bet_placed")]
    waits = [o for o in current if (o.get("action") or "").lower() == "wait"]
    skips = [o for o in current if (o.get("action") or "").lower() == "skip"]

    if current and not bet_recs:
        top_reason = (skips[0] if skips else waits[0] if waits else current[0]).get("reason") or "—"
        issues.append({
            "level": "warn",
            "text": f"אין כניסה כרגע — החלטה: {top_reason}",
        })

    recent_events: list[dict[str, str]] = []
    for row in repo.list_audit_logs(25):
        ev = getattr(row, "event", "") or ""
        if ev not in ("crypto_bet_placed", "crypto_bet_blocked", "crypto_bet_failed"):
            continue
        recent_events.append({
            "event": ev,
            "level": "ok" if ev == "crypto_bet_placed" else "err",
            "text": getattr(row, "message", "") or ev,
            "at": getattr(row, "created_at", None).isoformat(timespec="seconds") if getattr(row, "created_at", None) else "",
        })
        if len(recent_events) >= 8:
            break

    summary_parts: list[str] = []
    if issues:
        summary_parts.append(issues[0]["text"])
    elif bet_recs and live_on and running and auto_bet and trading_ready:
        summary_parts.append("יש המלצת כניסה — הבוט אמור לשלוח הזמנה ב-tick הבא")
    else:
        summary_parts.append("המערכת פעילה — ממתינה לתנאי כניסה")

    return {
        "summary_he": summary_parts[0],
        "issues": issues,
        "checks": checks,
        "recent_events": recent_events,
        "current_windows": len(current),
        "bet_recommendations": len(bet_recs),
        "wait_count": len(waits),
        "skip_count": len(skips),
    }


def _opportunity_row(market: dict[str, Any], *, exec_ctx: dict[str, Any] | None = None) -> dict[str, Any]:
    decision = market.get("decision") or {}
    progress = market.get("progress") or {}
    action = decision.get("action")
    bet_placed = bool(market.get("already_bet"))
    ctx = exec_ctx or {}
    blocker = _execution_blocker(
        live_on=bool(ctx.get("live_on")),
        runner_running=bool(ctx.get("runner_running")),
        auto_bet=bool(ctx.get("auto_bet")),
        trading_ready=bool(ctx.get("trading_ready")),
        kill_switch=bool(ctx.get("kill_switch")),
        decision_action=action,
        bet_placed=bet_placed,
    )
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
        "bet_placed": bet_placed,
        "bet_status": market.get("bet_status"),
        "execution_blocker": blocker,
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
    auto_bet = bool(runner_state.get("auto_bet", runner_status.get("auto_bet", True)))

    settings = crypto_cfg_with_experience(cfg, repo)
    experience = settings.get("_experience") or load_experience(repo)

    from politrade.execution.risk import RiskManager
    from politrade.api.clob_client import ClobClientWrapper

    clob = ClobClientWrapper(cfg)
    kill_switch = RiskManager(cfg, repo, clob).is_kill_switch_active()

    catalog = build_markets_catalog(cfg, repo=Repository(cfg))
    exec_ctx = {
        "live_on": live_on,
        "runner_running": bool(runner_status.get("running")),
        "auto_bet": auto_bet,
        "trading_ready": bool(catalog.get("trading_ready")),
        "kill_switch": kill_switch,
    }
    opportunities = [_opportunity_row(m, exec_ctx=exec_ctx) for m in catalog.get("markets", [])]
    opportunities.sort(key=lambda r: (not r["is_current"], r.get("window_ts") or 0, r.get("asset") or ""))

    recent_bets = [enrich_crypto_bet_dict(b) for b in repo.list_crypto_bets(50)]
    open_bets = [b for b in recent_bets if b.get("status") == "open"]
    summary = repo.crypto_bets_summary()

    cap = wallet_cap_usd(settings)
    exposure = repo.total_open_crypto_exposure()
    budget_left = None if cap <= 0 else max(0.0, round(cap - exposure, 2))

    diagnostics = _build_diagnostics(
        live_on=live_on,
        runner={**runner_status, **runner_info, "ticks": runner_state.get("ticks", runner_status.get("ticks", 0))},
        settings=settings,
        catalog=catalog,
        kill_switch=kill_switch,
        opportunities=opportunities,
        repo=repo,
    )

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
        "diagnostics": diagnostics,
    }
