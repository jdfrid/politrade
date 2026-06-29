"""Build live crypto dashboard payload."""

from __future__ import annotations

import time
from typing import Any

from politrade.config import AppConfig
from politrade.crypto.runner import get_crypto_runner
from politrade.crypto.strategy import crypto_cfg
from politrade.storage.repository import Repository
from politrade.web.wallet_activity import WalletActivitySummary, build_wallet_activity, wallet_activity_to_dict

_WALLET_CACHE: tuple[float, WalletActivitySummary] | None = None
_WALLET_CACHE_TTL = 15.0
_MARKETS_CACHE: tuple[float, dict[str, Any]] | None = None
_MARKETS_CACHE_TTL = 20.0


def invalidate_wallet_cache() -> None:
    global _WALLET_CACHE, _MARKETS_CACHE
    _WALLET_CACHE = None
    _MARKETS_CACHE = None


def _cached_markets_catalog(cfg: AppConfig, repo: Repository) -> dict[str, Any]:
    global _MARKETS_CACHE
    now = time.time()
    if _MARKETS_CACHE and now - _MARKETS_CACHE[0] < _MARKETS_CACHE_TTL:
        return _MARKETS_CACHE[1]
    catalog = build_markets_catalog(cfg, repo=repo)
    _MARKETS_CACHE = (now, catalog)
    return catalog


def _cached_wallet_activity(cfg: AppConfig, repo: Repository) -> WalletActivitySummary:
    global _WALLET_CACHE
    now = time.time()
    if _WALLET_CACHE and now - _WALLET_CACHE[0] < _WALLET_CACHE_TTL:
        return _WALLET_CACHE[1]
    activity = build_wallet_activity(cfg, repo)
    _WALLET_CACHE = (now, activity)
    return activity


def build_crypto_live(config: AppConfig | None = None) -> dict[str, Any]:
    from politrade.web.user_settings import get_effective_config

    cfg = config or get_effective_config()
    repo = Repository(cfg)
    runner = get_crypto_runner()
    state = runner.get_live_state()
    activity = _cached_wallet_activity(cfg, repo)

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
        "wallet": wallet_activity_to_dict(activity),
        "settings": {
            k: crypto_cfg(cfg).get(k)
            for k in (
                "bet_usd", "min_edge_pct", "max_entry_price", "min_move_pct",
                "no_bet_first_seconds", "no_bet_last_seconds", "auto_bet", "assets",
            )
        },
    }
