"""Aggregate simulation statistics for charts and dashboards."""

from __future__ import annotations

from typing import Any

from politrade.storage.models import SimBet, SimCycle, SimVariantBet
from politrade.storage.repository import Repository


def build_sim_stats(repo: Repository | None = None) -> dict[str, Any]:
    r = repo or Repository()
    bets = r.list_all_sim_bets()
    variant_bets = r.list_all_variant_bets()
    cycles = r.list_sim_cycles(limit=500)

    champion = _track_stats(bets, label="champion")
    variants = _track_stats(variant_bets, label="variants")
    timeline = _cycle_timeline(cycles)
    by_asset = _by_asset(bets)

    return {
        "champion": champion,
        "variants": variants,
        "combined": _combined_champion_variants(champion, variants),
        "timeline": timeline,
        "by_asset": by_asset,
        "cycles_count": len(cycles),
        "start_balance": r.get_sim_start_balance(),
        "current_balance": r.get_sim_balance(),
    }


def _track_stats(bets: list[SimBet] | list[SimVariantBet], *, label: str) -> dict[str, Any]:
    resolved = [b for b in bets if b.status in ("won", "lost")]
    open_bets = [b for b in bets if b.status == "open"]
    wins = [b for b in resolved if b.status == "won"]
    losses = [b for b in resolved if b.status == "lost"]

    total_invested = round(sum(b.bet_usd for b in bets), 2)
    resolved_invested = round(sum(b.bet_usd for b in resolved), 2)
    open_invested = round(sum(b.bet_usd for b in open_bets), 2)

    total_pnl = round(sum(b.realized_pnl or 0 for b in resolved), 2)
    profit_won = round(sum(b.realized_pnl or 0 for b in wins if (b.realized_pnl or 0) > 0), 2)
    loss_lost = round(abs(sum(b.realized_pnl or 0 for b in losses)), 2)

    win_count = len(wins)
    loss_count = len(losses)
    resolved_count = len(resolved)
    win_rate = round(win_count / resolved_count * 100, 1) if resolved_count else 0.0

    return {
        "label": label,
        "total_bets": len(bets),
        "open": len(open_bets),
        "resolved": resolved_count,
        "wins": win_count,
        "losses": loss_count,
        "win_rate_pct": win_rate,
        "total_invested_usd": total_invested,
        "resolved_invested_usd": resolved_invested,
        "open_invested_usd": open_invested,
        "total_pnl_usd": total_pnl,
        "profit_from_wins_usd": profit_won,
        "loss_from_losses_usd": loss_lost,
        "net_return_usd": round(resolved_invested + total_pnl, 2),
        "charts": {
            "win_loss_counts": {"wins": win_count, "losses": loss_count, "open": len(open_bets)},
            "money": {
                "invested": resolved_invested,
                "profit": profit_won,
                "loss": loss_lost,
                "net_pnl": total_pnl,
            },
        },
    }


def _combined_champion_variants(champion: dict, variants: dict) -> dict[str, Any]:
    wins = champion["wins"] + variants["wins"]
    losses = champion["losses"] + variants["losses"]
    resolved = wins + losses
    open_count = champion["open"] + variants["open"]
    invested = round(
        champion["total_invested_usd"] + variants["total_invested_usd"], 2
    )
    pnl = round(champion["total_pnl_usd"] + variants["total_pnl_usd"], 2)
    money = {
        "invested": round(
            champion["charts"]["money"]["invested"]
            + variants["charts"]["money"]["invested"],
            2,
        ),
        "profit": round(
            champion["charts"]["money"]["profit"]
            + variants["charts"]["money"]["profit"],
            2,
        ),
        "loss": round(
            champion["charts"]["money"]["loss"]
            + variants["charts"]["money"]["loss"],
            2,
        ),
        "net_pnl": pnl,
    }
    return {
        "label": "combined",
        "total_bets": champion["total_bets"] + variants["total_bets"],
        "open": open_count,
        "resolved": resolved,
        "wins": wins,
        "losses": losses,
        "win_rate_pct": round(wins / resolved * 100, 1) if resolved else 0.0,
        "total_invested_usd": invested,
        "total_pnl_usd": pnl,
        "charts": {
            "win_loss_counts": {
                "wins": wins,
                "losses": losses,
                "open": open_count,
            },
            "money": money,
        },
    }


def _cycle_timeline(cycles: list[SimCycle]) -> list[dict[str, Any]]:
    ordered = sorted(cycles, key=lambda c: c.window_ts)
    out: list[dict[str, Any]] = []
    for c in ordered:
        from datetime import datetime, timezone

        start = datetime.fromtimestamp(c.window_ts, tz=timezone.utc)
        out.append({
            "window_ts": c.window_ts,
            "label": start.strftime("%d/%m %H:%M"),
            "cycle_pnl": round(c.cycle_pnl, 2),
            "cumulative_pnl": round(c.cumulative_pnl, 2),
            "wins": c.wins,
            "losses": c.losses,
            "bets_taken": c.bets_taken,
        })
    return out


def _by_asset(bets: list[SimBet]) -> list[dict[str, Any]]:
    by: dict[str, dict[str, Any]] = {}
    for b in bets:
        a = b.asset.upper()
        row = by.setdefault(a, {"asset": a, "bets": 0, "wins": 0, "losses": 0, "invested": 0.0, "pnl": 0.0})
        row["bets"] += 1
        row["invested"] += b.bet_usd
        if b.status == "won":
            row["wins"] += 1
        elif b.status == "lost":
            row["losses"] += 1
        if b.realized_pnl is not None:
            row["pnl"] += b.realized_pnl
    for row in by.values():
        row["invested"] = round(row["invested"], 2)
        row["pnl"] = round(row["pnl"], 2)
        resolved = row["wins"] + row["losses"]
        row["win_rate_pct"] = round(row["wins"] / resolved * 100, 1) if resolved else 0.0
    return sorted(by.values(), key=lambda x: x["bets"], reverse=True)
