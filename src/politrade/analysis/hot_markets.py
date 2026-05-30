"""Discover high-volume markets and recent large buys."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from politrade.api.data_client import DataClient
from politrade.config import AppConfig
from politrade.logging_setup import get_logger

log = get_logger(__name__)


@dataclass
class HotMarketOpportunity:
    market_id: str
    title: str
    volume_24h: float
    leader_address: str
    leader_username: str | None
    side: str
    size_usd: float
    price: float
    traded_at: str


def fetch_hot_market_opportunities(
    config: AppConfig | None = None,
    *,
    market_limit: int = 5,
    trades_per_market: int = 5,
    min_trade_usd: float = 25,
) -> list[HotMarketOpportunity]:
    cfg = config or AppConfig()
    data = DataClient(cfg)
    results: list[HotMarketOpportunity] = []

    try:
        markets = data.get_trending_markets(limit=market_limit)
        for market in markets:
            condition_id = str(
                market.get("conditionId")
                or market.get("condition_id")
                or market.get("id")
                or ""
            )
            if not condition_id:
                continue
            title = str(market.get("question") or market.get("title") or condition_id[:16])
            try:
                vol = float(market.get("volume24hr") or market.get("volume24hrClob") or 0)
            except (TypeError, ValueError):
                vol = 0.0

            try:
                trades = data.get_trades(market=condition_id, limit=trades_per_market)
            except Exception as exc:
                log.warning("hot_market_trades_failed", market=condition_id, error=str(exc))
                continue

            for trade in trades:
                side = str(trade.get("side", "")).upper()
                if side != "BUY":
                    continue
                size = _trade_usd(trade)
                if size < min_trade_usd:
                    continue
                addr = str(
                    trade.get("proxyWallet") or trade.get("user") or trade.get("maker") or ""
                ).lower()
                name = trade.get("name") or trade.get("username") or trade.get("pseudonym")
                ts = trade.get("timestamp") or trade.get("createdAt") or ""
                results.append(
                    HotMarketOpportunity(
                        market_id=condition_id,
                        title=title[:120],
                        volume_24h=vol,
                        leader_address=addr,
                        leader_username=str(name) if name else None,
                        side=side,
                        size_usd=size,
                        price=float(trade.get("price", 0) or 0),
                        traded_at=str(ts)[:19] if ts else "—",
                    )
                )
    finally:
        data.close()

    results.sort(key=lambda x: (-x.volume_24h, -x.size_usd))
    return results[: market_limit * 2]


def _trade_usd(trade: dict[str, Any]) -> float:
    for key in ("usdcSize", "usdc_size", "size", "amount"):
        val = trade.get(key)
        if val is not None:
            try:
                return abs(float(val))
            except (TypeError, ValueError):
                pass
    price = float(trade.get("price", 0) or 0)
    size = float(trade.get("size", 0) or 0)
    return abs(price * size)
