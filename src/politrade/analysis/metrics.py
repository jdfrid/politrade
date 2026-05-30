"""Trader performance metrics from trade history."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any


@dataclass
class TraderMetrics:
    address: str
    trade_count: int
    win_rate: float
    total_volume_usd: float
    estimated_pnl: float
    roi: float
    sharpe_like: float
    max_drawdown: float
    avg_hold_hours: float
    trades_per_week: float
    recency_score: float
    pnl_30d: float
    recent_trades_24h: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _parse_ts(trade: dict[str, Any]) -> datetime | None:
    for key in ("timestamp", "createdAt", "created_at", "matchTime"):
        val = trade.get(key)
        if val is None:
            continue
        if isinstance(val, (int, float)):
            ts = float(val)
            if ts > 1e12:
                ts /= 1000
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        if isinstance(val, str):
            try:
                return datetime.fromisoformat(val.replace("Z", "+00:00"))
            except ValueError:
                continue
    return None


def _trade_usd(trade: dict[str, Any]) -> float:
    for key in ("usdcSize", "usdc_size", "size", "amount", "cash"):
        val = trade.get(key)
        if val is not None:
            try:
                return abs(float(val))
            except (TypeError, ValueError):
                pass
    price = float(trade.get("price", 0) or 0)
    size = float(trade.get("size", 0) or trade.get("shares", 0) or 0)
    return abs(price * size)


def _trade_pnl_proxy(trade: dict[str, Any]) -> float:
    for key in ("realizedPnl", "realized_pnl", "pnl"):
        val = trade.get(key)
        if val is not None:
            try:
                return float(val)
            except (TypeError, ValueError):
                pass
    side = str(trade.get("side", "")).upper()
    usd = _trade_usd(trade)
    if side == "SELL":
        return usd * 0.01
    return -usd * 0.005


def compute_metrics(
    address: str,
    trades: list[dict[str, Any]],
    *,
    lookback_days: int = 90,
) -> TraderMetrics:
    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    recent_cutoff = datetime.now(timezone.utc) - timedelta(days=30)

    filtered: list[tuple[datetime, dict[str, Any]]] = []
    for t in trades:
        ts = _parse_ts(t)
        if ts and ts >= cutoff:
            filtered.append((ts, t))

    filtered.sort(key=lambda x: x[0])
    trade_count = len(filtered)

    if trade_count == 0:
        return TraderMetrics(
            address=address,
            trade_count=0,
            win_rate=0.0,
            total_volume_usd=0.0,
            estimated_pnl=0.0,
            roi=0.0,
            sharpe_like=0.0,
            max_drawdown=0.0,
            avg_hold_hours=0.0,
            trades_per_week=0.0,
            recency_score=0.0,
            pnl_30d=0.0,
            recent_trades_24h=0,
        )

    cutoff_24h = datetime.now(timezone.utc) - timedelta(hours=24)
    recent_trades_24h = sum(1 for ts, _ in filtered if ts >= cutoff_24h)

    pnls = [_trade_pnl_proxy(t) for _, t in filtered]
    volumes = [_trade_usd(t) for _, t in filtered]
    total_volume = sum(volumes)
    estimated_pnl = sum(pnls)
    wins = sum(1 for p in pnls if p > 0)
    win_rate = wins / trade_count if trade_count else 0.0
    roi = estimated_pnl / total_volume if total_volume > 0 else 0.0

    daily_returns: dict[str, float] = defaultdict(float)
    for (ts, t), pnl in zip(filtered, pnls):
        daily_returns[ts.date().isoformat()] += pnl

    returns = list(daily_returns.values())
    if len(returns) > 1:
        mean_r = sum(returns) / len(returns)
        var = sum((r - mean_r) ** 2 for r in returns) / (len(returns) - 1)
        std = var**0.5
        sharpe_like = mean_r / std if std > 0 else 0.0
    else:
        sharpe_like = 0.0

    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for pnl in pnls:
        equity += pnl
        peak = max(peak, equity)
        dd = (peak - equity) / peak if peak > 0 else 0.0
        max_dd = max(max_dd, dd)

    pnl_30d = sum(p for (ts, _), p in zip(filtered, pnls) if ts >= recent_cutoff)
    span_days = max((filtered[-1][0] - filtered[0][0]).days, 1)
    trades_per_week = trade_count / (span_days / 7)

    recency_trades = sum(1 for ts, _ in filtered if ts >= recent_cutoff)
    recency_score = min(recency_trades / max(trade_count, 1), 1.0)

    return TraderMetrics(
        address=address,
        trade_count=trade_count,
        win_rate=win_rate,
        total_volume_usd=total_volume,
        estimated_pnl=estimated_pnl,
        roi=roi,
        sharpe_like=sharpe_like,
        max_drawdown=max_dd,
        avg_hold_hours=24.0,
        trades_per_week=trades_per_week,
        recency_score=recency_score,
        pnl_30d=pnl_30d,
        recent_trades_24h=recent_trades_24h,
    )
