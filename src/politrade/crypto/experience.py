"""Learn from sim + live resolved bets to tune entry timing and per-asset edge."""

from __future__ import annotations

import json
import statistics
from datetime import datetime, timezone
from typing import Any

from politrade.crypto.strategy import DecisionAction, StrategyDecision
from politrade.crypto.window import BetSide, CryptoWindow, WINDOW_SECONDS
from politrade.storage.repository import Repository

EXPERIENCE_STATE_KEY = "crypto_experience_v1"
MIN_SAMPLES = 8


def _entry_seconds(bet: Any) -> int | None:
    sec = getattr(bet, "seconds_at_entry", None)
    if sec is not None:
        return int(sec)
    created = getattr(bet, "created_at", None)
    wts = getattr(bet, "window_ts", None)
    if created and wts:
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        return max(0, int(created.timestamp()) - int(wts))
    return None


def _collect_resolved(repo: Repository) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for bet in repo.list_sim_bets(limit=400):
        if bet.status not in ("won", "lost"):
            continue
        rows.append({
            "source": "sim",
            "asset": bet.asset.lower(),
            "side": bet.side.lower(),
            "won": bet.status == "won",
            "pnl": float(bet.realized_pnl or 0),
            "edge_pct": bet.edge_pct,
            "entry_sec": _entry_seconds(bet),
        })
    for bet in repo.list_crypto_bets(limit=200):
        if bet.status not in ("won", "lost", "redeemed"):
            continue
        rows.append({
            "source": "live",
            "asset": bet.asset.lower(),
            "side": bet.side.lower(),
            "won": bet.status in ("won", "redeemed"),
            "pnl": float(bet.realized_pnl or 0),
            "edge_pct": bet.edge_pct,
            "entry_sec": _entry_seconds(bet),
        })
    return rows


def _summarize_asset(records: list[dict[str, Any]]) -> dict[str, Any]:
    if not records:
        return {"count": 0, "wins": 0, "win_rate": 0, "pnl": 0.0}
    wins = sum(1 for r in records if r["won"])
    pnl = round(sum(r["pnl"] for r in records), 2)
    win_secs = [r["entry_sec"] for r in records if r["won"] and r["entry_sec"] is not None]
    up = [r for r in records if r["side"] == BetSide.UP.value]
    down = [r for r in records if r["side"] == BetSide.DOWN.value]
    return {
        "count": len(records),
        "wins": wins,
        "win_rate": round(wins / len(records) * 100, 1),
        "pnl": pnl,
        "sim_count": sum(1 for r in records if r["source"] == "sim"),
        "live_count": sum(1 for r in records if r["source"] == "live"),
        "median_entry_sec_wins": int(statistics.median(win_secs)) if win_secs else None,
        "up_win_rate": round(sum(1 for r in up if r["won"]) / len(up) * 100, 1) if up else None,
        "down_win_rate": round(sum(1 for r in down if r["won"]) / len(down) * 100, 1) if down else None,
    }


def build_experience(repo: Repository | None = None) -> dict[str, Any]:
    r = repo or Repository()
    records = _collect_resolved(r)
    by_asset: dict[str, dict[str, Any]] = {}
    for asset in sorted({rec["asset"] for rec in records}):
        by_asset[asset] = _summarize_asset([rec for rec in records if rec["asset"] == asset])

    ranked = sorted(
        by_asset.items(),
        key=lambda kv: (kv[1]["win_rate"], kv[1]["pnl"]),
        reverse=True,
    )
    best_asset = ranked[0][0] if ranked else None
    worst_asset = ranked[-1][0] if len(ranked) > 1 else None

    return {
        "total_resolved": len(records),
        "sim_resolved": sum(1 for rec in records if rec["source"] == "sim"),
        "live_resolved": sum(1 for rec in records if rec["source"] == "live"),
        "by_asset": by_asset,
        "best_asset": best_asset,
        "worst_asset": worst_asset,
        "lesson_he": _format_lesson(by_asset, best_asset, worst_asset, len(records)),
    }


def refresh_experience(repo: Repository | None = None) -> dict[str, Any]:
    r = repo or Repository()
    summary = build_experience(r)
    r.set_state(EXPERIENCE_STATE_KEY, json.dumps(summary, ensure_ascii=False))
    return summary


def load_experience(repo: Repository | None = None) -> dict[str, Any]:
    r = repo or Repository()
    raw = r.get_state(EXPERIENCE_STATE_KEY)
    if raw:
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass
    return refresh_experience(r)


def adjusted_min_edge(base: float, asset: str, exp: dict[str, Any]) -> tuple[float, str | None]:
    stats = (exp.get("by_asset") or {}).get(asset.lower())
    if not stats or stats.get("count", 0) < MIN_SAMPLES:
        return base, None
    wr = float(stats["win_rate"])
    if wr >= 62:
        return max(0.0, base - 3.0), f"ניסיון: {asset.upper()} WR {wr:.0f}% — edge מותאם ל-{max(0, base - 3):.0f}%"
    if wr <= 38:
        return base + 5.0, f"ניסיון: {asset.upper()} WR {wr:.0f}% — edge מחמיר ל-{base + 5:.0f}%"
    return base, None


def apply_experience_to_decision(
    decision: StrategyDecision,
    window: CryptoWindow,
    *,
    base_min_edge: float,
    experience: dict[str, Any] | None,
) -> StrategyDecision:
    """Use sim+live history to tighten/relax edge and warn on bad timing."""
    if decision.action != DecisionAction.BET or not experience:
        return decision

    asset = window.asset.value.lower()
    stats = (experience.get("by_asset") or {}).get(asset)
    if not stats or stats.get("count", 0) < MIN_SAMPLES:
        return decision

    eff_edge, edge_note = adjusted_min_edge(base_min_edge, asset, experience)
    if edge_note and decision.edge_pct is not None and decision.edge_pct < eff_edge:
        return StrategyDecision(
            action=DecisionAction.SKIP,
            side=decision.side,
            token_id=decision.token_id,
            entry_ask=decision.entry_ask,
            edge_pct=decision.edge_pct,
            reason=f"edge {decision.edge_pct:.1f}% < {eff_edge:.0f}% (למידה מ-{stats['count']} עסקאות)",
            confidence=decision.confidence * 0.7,
            seconds_elapsed=decision.seconds_elapsed,
            rationale_he=(decision.rationale_he or "") + f"\n{edge_note}",
        )

    elapsed = decision.seconds_elapsed or 0
    median = stats.get("median_entry_sec_wins")
    notes: list[str] = []
    if median is not None and stats.get("wins", 0) >= 5:
        if elapsed < median - 20:
            notes.append(f"כניסה מוקדמת ל-{asset.upper()} — זכיות בדרך כלל אחרי ~{median}s")
        elif abs(elapsed - median) <= 15:
            notes.append(f"תזמון טוב ל-{asset.upper()} (ממוצע זכיות ~{median}s)")

    up_wr = stats.get("up_win_rate")
    down_wr = stats.get("down_win_rate")
    if decision.side == BetSide.UP and up_wr is not None and down_wr is not None:
        if up_wr + 15 < down_wr:
            notes.append(f"על {asset.upper()} DOWN היסטורית חזק יותר ({down_wr:.0f}% vs UP {up_wr:.0f}%)")
    elif decision.side == BetSide.DOWN and up_wr is not None and down_wr is not None:
        if down_wr + 15 < up_wr:
            notes.append(f"על {asset.upper()} UP היסטורית חזק יותר ({up_wr:.0f}% vs DOWN {down_wr:.0f}%)")

    best = experience.get("best_asset")
    worst = experience.get("worst_asset")
    if best and worst and asset == worst and best != worst:
        best_stats = experience["by_asset"].get(best, {})
        notes.append(
            f"לפי ניסיון: {best.upper()} מוביל (WR {best_stats.get('win_rate', 0):.0f}%)"
        )

    if notes:
        extra = " · ".join(notes)
        decision.rationale_he = ((decision.rationale_he or "") + "\n" + extra).strip()
        if edge_note:
            decision.rationale_he += f"\n{edge_note}"

    return decision


def _format_lesson(
    by_asset: dict[str, dict[str, Any]],
    best: str | None,
    worst: str | None,
    total: int,
) -> str:
    if total < MIN_SAMPLES:
        return f"ניסיון: {total} עסקאות — צריך לפחות {MIN_SAMPLES} לפני התאמות."
    lines = [f"ניסיון מצטבר: {total} עסקאות (סימולציה + אמיתי)"]
    for asset, st in sorted(by_asset.items(), key=lambda kv: kv[1]["win_rate"], reverse=True):
        med = st.get("median_entry_sec_wins")
        med_txt = f" · כניסה מוצלחת ~{med}s" if med else ""
        lines.append(
            f"• {asset.upper()}: WR {st['win_rate']:.0f}% · PnL ${st['pnl']:+.2f}"
            f" · sim {st['sim_count']} live {st['live_count']}{med_txt}"
        )
    if best and worst and best != worst:
        lines.append(f"מוביל: {best.upper()} · חלש: {worst.upper()}")
    return "\n".join(lines)
