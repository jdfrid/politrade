"""Catalog of open crypto 5m markets with buy readiness."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from politrade.api.clob_client import ClobClientWrapper
from politrade.api.data_client import DataClient
from politrade.config import AppConfig
from politrade.crypto.price_feed import (
    OracleSnapshot,
    TokenPrices,
    edge_pct_from_ask,
    fetch_token_prices,
    get_price_feed,
)
from politrade.crypto.window import BetSide, CryptoAsset, WindowPhase, compute_window_ts, enabled_assets, fetch_window_market
from politrade.storage.repository import Repository


@dataclass
class SideBuyStatus:
    side: str
    token_id: str
    ask: float | None
    edge_pct: float | None
    can_buy: bool
    block_reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "side": self.side,
            "token_id": self.token_id,
            "ask": self.ask,
            "edge_pct": round(self.edge_pct, 2) if self.edge_pct is not None else None,
            "can_buy": self.can_buy,
            "block_reason": self.block_reason,
        }


def _fmt_window_time(window_ts: int) -> str:
    start = datetime.fromtimestamp(window_ts, tz=timezone.utc)
    end = datetime.fromtimestamp(window_ts + 300, tz=timezone.utc)
    return f"{start.strftime('%H:%M')}–{end.strftime('%H:%M')} UTC"


def assess_side_buy(
    *,
    side: BetSide,
    window_closed: bool,
    phase: WindowPhase,
    token_id: str,
    ask: float | None,
    trading_ready: bool,
    already_bet: bool,
    min_bet_usd: float,
    cash_usd: float | None,
    has_liquidity: bool,
) -> SideBuyStatus:
    blocks: list[str] = []
    if not trading_ready:
        blocks.append("CLOB לא מחובר")
    if window_closed or phase == WindowPhase.CLOSED:
        blocks.append("שוק סגור")
    if already_bet:
        blocks.append("כבר הימרת בחלון")
    if not token_id:
        blocks.append("חסר token")
    if ask is None:
        blocks.append("אין מחיר")
    elif ask <= 0.01 or ask >= 0.99:
        blocks.append("מחיר לא סחיר")
    if not has_liquidity:
        blocks.append("אין נזילות")
    if cash_usd is not None and cash_usd < min_bet_usd:
        blocks.append(f"יתרה נמוכה (<${min_bet_usd:.0f})")

    return SideBuyStatus(
        side=side.value,
        token_id=token_id,
        ask=ask,
        edge_pct=edge_pct_from_ask(ask),
        can_buy=len(blocks) == 0,
        block_reason=" · ".join(blocks) if blocks else "",
    )


def build_markets_catalog(
    config: AppConfig,
    *,
    repo: Repository | None = None,
    clob: ClobClientWrapper | None = None,
) -> dict[str, Any]:
    from politrade.crypto.strategy import crypto_cfg

    repo = repo or Repository(config)
    clob = clob or ClobClientWrapper(config)
    cfg = crypto_cfg(config)
    ahead = int(cfg.get("markets_ahead", 4))
    min_bet = float(cfg.get("bet_usd", 5))
    enabled = {a.value for a in enabled_assets(config)}

    cash: float | None = None
    trading_ready = clob.is_configured
    if clob.is_configured:
        details = clob.get_balance_details()
        cash = details.get("balance")
        if details.get("error") and cash is None:
            trading_ready = False

    feed = get_price_feed()
    data = DataClient(config)
    now_ts = compute_window_ts()
    markets: list[dict[str, Any]] = []

    try:
        catalog_assets = list(CryptoAsset)
        for asset in catalog_assets:
            for i in range(0, ahead + 1):
                wts = now_ts + i * 300
                window = fetch_window_market(asset, wts, config=config, data=data)
                if window is None:
                    continue
                if window.closed:
                    continue
                if asset.value not in enabled and i > 1:
                    continue

                phase = window.phase()
                tokens = fetch_token_prices(clob, window) if clob.is_configured else TokenPrices()
                oracle = feed.get_snapshot(window) if i == 0 else OracleSnapshot(
                    asset=asset, window_ts=wts
                )
                already = repo.has_crypto_bet_for_window(asset.value, wts)

                up_ask = tokens.up_ask or tokens.up_mid
                down_ask = tokens.down_ask or tokens.down_mid
                up_liq = up_ask is not None and 0.02 <= up_ask <= 0.98
                down_liq = down_ask is not None and 0.02 <= down_ask <= 0.98

                up_status = assess_side_buy(
                    side=BetSide.UP,
                    window_closed=window.closed,
                    phase=phase,
                    token_id=window.up_token_id,
                    ask=up_ask,
                    trading_ready=trading_ready,
                    already_bet=already,
                    min_bet_usd=min_bet,
                    cash_usd=cash,
                    has_liquidity=up_liq,
                )
                down_status = assess_side_buy(
                    side=BetSide.DOWN,
                    window_closed=window.closed,
                    phase=phase,
                    token_id=window.down_token_id,
                    ask=down_ask,
                    trading_ready=trading_ready,
                    already_bet=already,
                    min_bet_usd=min_bet,
                    cash_usd=cash,
                    has_liquidity=down_liq,
                )

                markets.append({
                    "asset": asset.value,
                    "asset_label": asset.label,
                    "window_ts": wts,
                    "slug": window.slug,
                    "title": window.title or window.slug,
                    "phase": phase.value,
                    "seconds_remaining": window.seconds_remaining(),
                    "window_time": _fmt_window_time(wts),
                    "bot_enabled": asset.value in enabled,
                    "already_bet": already,
                    "oracle_delta_pct": oracle.delta_pct,
                    "up": up_status.to_dict(),
                    "down": down_status.to_dict(),
                    "any_can_buy": up_status.can_buy or down_status.can_buy,
                })
    finally:
        data.close()

    markets.sort(key=lambda m: (m["asset"], m["window_ts"]))
    open_count = len(markets)
    buyable_count = sum(1 for m in markets if m["any_can_buy"])

    return {
        "updated_at": time.time(),
        "trading_ready": trading_ready,
        "cash_usd": cash,
        "min_bet_usd": min_bet,
        "markets_ahead": ahead,
        "open_count": open_count,
        "buyable_count": buyable_count,
        "markets": markets,
    }
