"""Build live crypto dashboard payload."""

from __future__ import annotations

from typing import Any

from politrade.api.clob_client import ClobClientWrapper
from politrade.config import AppConfig
from politrade.crypto.runner import get_crypto_runner
from politrade.crypto.strategy import crypto_cfg
from politrade.storage.repository import Repository
from politrade.wallet_store import wallet_status


def build_crypto_live(config: AppConfig | None = None) -> dict[str, Any]:
    from politrade.web.user_settings import get_effective_config

    cfg = config or get_effective_config()
    repo = Repository(cfg)
    runner = get_crypto_runner()
    state = runner.get_live_state()
    clob = ClobClientWrapper(cfg)
    cash = None
    if clob.is_configured:
        cash = clob.get_balance_details().get("balance")

    bets = []
    for b in repo.list_crypto_bets(30):
        bets.append({
            "id": b.id,
            "asset": b.asset.upper(),
            "window_ts": b.window_ts,
            "slug": b.slug,
            "side": b.side,
            "bet_usd": b.bet_usd,
            "entry_price": b.entry_price,
            "edge_pct": b.edge_pct,
            "status": b.status,
            "realized_pnl": b.realized_pnl,
            "open_oracle_price": b.open_oracle_price,
            "oracle_close_price": b.oracle_close_price,
            "created_at": b.created_at.isoformat() if b.created_at else "",
        })

    return {
        "runner": runner.status,
        "state": state,
        "bets": bets,
        "summary": repo.crypto_bets_summary(),
        "wallet": {
            "configured": wallet_status(cfg)["configured"],
            "cash_usd": cash,
        },
        "settings": {
            k: crypto_cfg(cfg).get(k)
            for k in (
                "bet_usd", "min_edge_pct", "max_entry_price", "min_move_pct",
                "no_bet_first_seconds", "no_bet_last_seconds", "auto_bet", "assets",
            )
        },
    }
