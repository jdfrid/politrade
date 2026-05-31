"""Score and rank traders."""

from __future__ import annotations

from typing import Any

from politrade.analysis.metrics import TraderMetrics
from politrade.config import AppConfig


def score_trader(metrics: TraderMetrics, config: AppConfig | None = None) -> float:
    cfg = config or AppConfig()
    weights = cfg.scoring.get("weights", {})
    w_pnl = float(weights.get("pnl", 0.25))
    w_wr = float(weights.get("win_rate", 0.25))
    w_sharpe = float(weights.get("sharpe", 0.20))
    w_recency = float(weights.get("recency", 0.15))
    w_dd = float(weights.get("drawdown_penalty", 0.10))
    w_over = float(weights.get("overtrading_penalty", 0.05))

    pnl_norm = min(max(metrics.estimated_pnl / 1000, -1), 1) * 50 + 50
    wr_score = metrics.win_rate * 100
    sharpe_score = min(max(metrics.sharpe_like * 20, -50), 50) + 50
    recency_score = metrics.recency_score * 100
    dd_penalty = metrics.max_drawdown * 100
    over_penalty = min(metrics.trades_per_week / 50, 1) * 50

    raw = (
        w_pnl * pnl_norm
        + w_wr * wr_score
        + w_sharpe * sharpe_score
        + w_recency * recency_score
        - w_dd * dd_penalty
        - w_over * over_penalty
    )
    return max(0.0, min(100.0, raw))


def passes_filters(metrics: TraderMetrics, config: AppConfig | None = None) -> bool:
    cfg = config or AppConfig()
    leaders = cfg.leaders
    min_trades = int(leaders.get("min_trades", 50))
    min_wr = float(leaders.get("min_win_rate", 0.55))
    max_dd = float(leaders.get("max_drawdown", 0.30))

    if metrics.trade_count < min_trades:
        return False
    if metrics.win_rate < min_wr:
        return False
    if metrics.max_drawdown > max_dd:
        return False
    if metrics.pnl_30d <= 0:
        min_recent = int(leaders.get("min_recent_trades_24h", 5))
        if metrics.recent_trades_24h < min_recent:
            return False
    return True


def rank_traders(
    profiles: list[tuple[TraderMetrics, str | None]],
    config: AppConfig | None = None,
) -> list[dict[str, Any]]:
    cfg = config or AppConfig()
    top_k = int(cfg.leaders.get("top_k", 5))
    min_score = float(cfg.copy.get("min_leader_score", 70))

    scored: list[dict[str, Any]] = []
    for metrics, username in profiles:
        if not passes_filters(metrics, cfg):
            continue
        score = score_trader(metrics, cfg)
        recent_bonus = min(metrics.recent_trades_24h * 1.5, 12.0)
        score = min(100.0, score + recent_bonus)
        if score < min_score:
            continue
        scored.append(
            {
                "address": metrics.address,
                "username": username,
                "score": score,
                "metrics": metrics.to_dict(),
            }
        )

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top_k]


def rank_traders_relaxed(
    profiles: list[tuple[TraderMetrics, str | None]],
    config: AppConfig | None = None,
) -> list[dict[str, Any]]:
    """Fallback when strict filters find nobody — keep traders with real activity + score."""
    cfg = config or AppConfig()
    top_k = int(cfg.leaders.get("top_k", 5))
    min_score = float(cfg.copy.get("min_leader_score", 60))
    min_trades = max(5, int(cfg.leaders.get("min_trades", 20)) // 4)

    scored: list[dict[str, Any]] = []
    for metrics, username in profiles:
        if metrics.trade_count < min_trades:
            continue
        score = score_trader(metrics, cfg)
        recent_bonus = min(metrics.recent_trades_24h * 1.5, 12.0)
        score = min(100.0, score + recent_bonus)
        if score < min_score:
            continue
        scored.append(
            {
                "address": metrics.address,
                "username": username,
                "score": score,
                "metrics": metrics.to_dict(),
            }
        )

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top_k]
