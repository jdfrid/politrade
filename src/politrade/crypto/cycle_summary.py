"""End-of-cycle Hebrew summaries for simulation."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from politrade.config import AppConfig
from politrade.crypto.sim_mode import set_readiness_score
from politrade.crypto.strategy import crypto_cfg
from politrade.storage.models import SimBet, SimCycle, SimDecision
from politrade.storage.repository import Repository


def build_cycle_summary(
    window_ts: int,
    config: AppConfig | None = None,
    repo: Repository | None = None,
) -> SimCycle | None:
    from politrade.config import AppConfig

    cfg = config or AppConfig()
    r = repo or Repository(cfg)
    if r.get_sim_cycle(window_ts) is not None:
        return r.get_sim_cycle(window_ts)

    decisions = r.list_sim_decisions_for_window(window_ts)
    bets = r.get_sim_bets_for_window(window_ts)
    resolved = [b for b in bets if b.status in ("won", "lost")]
    wins = sum(1 for b in resolved if b.status == "won")
    losses = len(resolved) - wins
    cycle_pnl = round(sum(b.realized_pnl or 0 for b in resolved), 2)

    bets_taken = len(bets)
    skips = sum(1 for d in decisions if d.action == "skip")
    waits = sum(1 for d in decisions if d.action == "wait")

    prev = r.list_sim_cycles(limit=1)
    prev_cycle = prev[0] if prev else None
    cumulative = round(r.get_sim_cumulative_pnl(), 2)

    all_resolved = r.list_sim_bets(limit=500)
    all_done = [b for b in all_resolved if b.status in ("won", "lost")]
    win_rate = (wins / len(resolved) * 100) if resolved else 0.0
    overall_wr = (
        sum(1 for b in all_done if b.status == "won") / len(all_done) * 100
        if all_done else 0.0
    )

    win_rate_delta = None
    pnl_delta = None
    if prev_cycle:
        win_rate_delta = round(overall_wr - prev_cycle.win_rate, 1)
        pnl_delta = round(cumulative - prev_cycle.cumulative_pnl, 2)

    params_before = _current_params(cfg)
    summary_he = _format_summary(
        window_ts, decisions, bets, resolved, wins, losses, cycle_pnl, cumulative
    )
    lessons_he = _format_lessons(decisions, resolved)

    readiness = _compute_readiness(
        overall_wr, cumulative, len(all_done), r.list_sim_cycles(limit=20)
    )
    set_readiness_score(r, readiness)

    cycle = r.create_sim_cycle(
        window_ts=window_ts,
        markets_total=len(decisions),
        bets_taken=bets_taken,
        bets_skipped=skips,
        waits=waits,
        wins=wins,
        losses=losses,
        cycle_pnl=cycle_pnl,
        cumulative_pnl=cumulative,
        win_rate=round(overall_wr, 1),
        win_rate_delta=win_rate_delta,
        pnl_delta=pnl_delta,
        summary_he=summary_he,
        lessons_he=lessons_he,
        params_before=json.dumps(params_before, ensure_ascii=False),
        params_after=json.dumps(params_before, ensure_ascii=False),
        readiness_score=readiness,
    )
    return cycle


def update_cycle_params_after(
    cycle: SimCycle,
    params_after: dict[str, Any],
    repo: Repository,
) -> None:
    with repo.session() as s:
        row = s.get(SimCycle, cycle.id)
        if row:
            row.params_after = json.dumps(params_after, ensure_ascii=False)
            s.commit()


def _current_params(config: AppConfig) -> dict[str, Any]:
    c = crypto_cfg(config)
    return {
        "bet_usd": c.get("bet_usd"),
        "min_edge_pct": c.get("min_edge_pct"),
        "max_entry_price": c.get("max_entry_price"),
        "min_move_pct": c.get("min_move_pct"),
        "no_bet_first_seconds": c.get("no_bet_first_seconds"),
        "no_bet_last_seconds": c.get("no_bet_last_seconds"),
        "strategy_mode": c.get("strategy_mode"),
    }


def _format_summary(
    window_ts: int,
    decisions: list[SimDecision],
    bets: list[SimBet],
    resolved: list[SimBet],
    wins: int,
    losses: int,
    cycle_pnl: float,
    cumulative: float,
) -> str:
    start = datetime.fromtimestamp(window_ts, tz=timezone.utc).strftime("%H:%M")
    end = datetime.fromtimestamp(window_ts + 300, tz=timezone.utc).strftime("%H:%M UTC")
    lines = [
        f"חלון {start}–{end}: {len(decisions)} שווקים, {len(bets)} הימורים, "
        f"{wins} זכיות / {losses} הפסדים, PnL סיבוב: ${cycle_pnl:+.2f}, מצטבר: ${cumulative:+.2f}",
    ]
    for bet in bets:
        status = "זכייה" if bet.status == "won" else "הפסד" if bet.status == "lost" else "פתוח"
        lines.append(
            f"• {bet.asset.upper()}: {bet.side.upper()} ${bet.bet_usd:.0f} — {status}"
            + (f" ({bet.realized_pnl:+.2f}$)" if bet.realized_pnl is not None else "")
        )
    notable_skips = [d for d in decisions if d.action == "skip"][:3]
    for d in notable_skips:
        lines.append(f"• דולג {d.asset.upper()}: {d.reason}")
    return "\n".join(lines)


def _format_lessons(decisions: list[SimDecision], resolved: list[SimBet]) -> str:
    edge_skips = sum(1 for d in decisions if d.action == "skip" and d.reason and "edge" in d.reason.lower())
    wait_count = sum(1 for d in decisions if d.action == "wait")
    losses = sum(1 for b in resolved if b.status == "lost")
    lines: list[str] = []
    if edge_skips >= len(decisions) * 0.4 and decisions:
        lines.append(f"רוב השווקים ({edge_skips}) נדחו בגלל edge — שקול להוריד min_edge_pct")
    if wait_count >= len(decisions) * 0.5 and decisions:
        lines.append(f"הרבה המתנות ({wait_count}) — אולי תזוזת Chainlink נמוכה מדי")
    if losses > len(resolved) * 0.5 and resolved:
        lines.append(f"הרבה הפסדים ({losses}/{len(resolved)}) — שקול להעלות min_move_pct")
    if not lines:
        lines.append("הפרמטרים יציבים — המשך לנטר")
    return "\n".join(lines)


def _compute_readiness(
    win_rate: float,
    cumulative_pnl: float,
    resolved_count: int,
    recent_cycles: list[SimCycle],
) -> float:
    score = 0.0
    score += min(40.0, win_rate * 0.5)
    score += min(30.0, max(0.0, cumulative_pnl) / 2.0)
    score += min(20.0, resolved_count * 2.0)
    if len(recent_cycles) >= 5:
        recent_pnl = sum(c.cycle_pnl for c in recent_cycles[:5])
        if recent_pnl > 0:
            score += 10.0
    return round(min(100.0, score), 1)


def cycle_to_dict(cycle: SimCycle) -> dict[str, Any]:
    return {
        "window_ts": cycle.window_ts,
        "markets_total": cycle.markets_total,
        "bets_taken": cycle.bets_taken,
        "bets_skipped": cycle.bets_skipped,
        "waits": cycle.waits,
        "wins": cycle.wins,
        "losses": cycle.losses,
        "cycle_pnl": cycle.cycle_pnl,
        "cumulative_pnl": cycle.cumulative_pnl,
        "win_rate": cycle.win_rate,
        "win_rate_delta": cycle.win_rate_delta,
        "pnl_delta": cycle.pnl_delta,
        "summary_he": cycle.summary_he,
        "lessons_he": cycle.lessons_he,
        "params_before": cycle.params_before,
        "params_after": cycle.params_after,
        "readiness_score": cycle.readiness_score,
        "created_at": cycle.created_at.isoformat() if cycle.created_at else "",
    }
