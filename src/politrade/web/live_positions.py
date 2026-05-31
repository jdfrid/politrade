"""Build live position payloads for API and UI."""

from __future__ import annotations

from typing import Any

from politrade.api.clob_client import ClobClientWrapper
from politrade.config import AppConfig
from politrade.execution.position_valuation import ExitTargets, value_position
from politrade.storage.models import Position
from politrade.storage.repository import Repository


def build_live_position(
    pos: Position,
    *,
    config: AppConfig,
    repo: Repository,
    clob: ClobClientWrapper | None = None,
    include_snapshots: bool = True,
) -> dict[str, Any]:
    clob = clob or ClobClientWrapper(config)
    targets = ExitTargets.from_config(config.exit)
    price = pos.entry_price
    if clob.is_configured:
        mid = clob.get_mid_price(pos.token_id)
        if mid is not None:
            price = mid
    valuation = value_position(pos, price, targets=targets)

    snapshots: list[dict[str, Any]] = []
    if include_snapshots:
        for snap in reversed(repo.list_snapshots(pos.id, limit=60)):
            recorded = snap.recorded_at.isoformat() if snap.recorded_at else ""
            snapshots.append({"t": recorded, "pnl_pct": round(snap.pnl_pct, 2)})

    opened = pos.opened_at.isoformat() if pos.opened_at else ""
    title = pos.market_title or f"{pos.market_id[:20]}…"

    return {
        "id": pos.id,
        "title": title,
        "market_id": pos.market_id,
        "entry_cost_usd": round(pos.entry_cost_usd, 2),
        "entry_price": round(pos.entry_price, 4),
        "shares": round(pos.shares, 4),
        "current_price": round(valuation.current_price, 4),
        "current_value_usd": round(valuation.current_value_usd, 2),
        "pnl_usd": round(valuation.pnl_usd, 2),
        "pnl_pct": round(valuation.pnl_pct, 2),
        "take_profit_pct": targets.take_profit_pct,
        "stop_loss_pct": targets.stop_loss_pct,
        "progress_to_tp": round(valuation.progress_to_tp, 1),
        "take_profit_target_usd": round(valuation.take_profit_target_usd, 2),
        "stop_loss_target_usd": round(valuation.stop_loss_target_usd, 2),
        "leader_address": pos.leader_address,
        "opened_at": opened,
        "snapshots": snapshots,
    }


def build_live_positions_summary(
    config: AppConfig,
    repo: Repository | None = None,
) -> dict[str, Any]:
    repo = repo or Repository(config)
    clob = ClobClientWrapper(config)
    positions = repo.get_open_positions()
    items = [
        build_live_position(p, config=config, repo=repo, clob=clob, include_snapshots=True)
        for p in positions
    ]
    total_entry = sum(p["entry_cost_usd"] for p in items)
    total_value = sum(p["current_value_usd"] for p in items)
    total_pnl = sum(p["pnl_usd"] for p in items)
    return {
        "positions": items,
        "count": len(items),
        "total_entry_usd": round(total_entry, 2),
        "total_value_usd": round(total_value, 2),
        "total_pnl_usd": round(total_pnl, 2),
        "monitor_seconds": int(config.exit.get("monitor_seconds", 20)),
    }
