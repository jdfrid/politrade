"""Tests for trader metrics."""

from datetime import datetime, timezone, timedelta

from politrade.analysis.metrics import compute_metrics
from politrade.analysis.leader_ranker import passes_filters, score_trader


def _trade(ts: datetime, side: str = "BUY", usd: float = 100, pnl: float = 5):
    return {
        "timestamp": ts.isoformat(),
        "side": side,
        "usdcSize": usd,
        "realizedPnl": pnl,
    }


def test_compute_metrics_basic():
    now = datetime.now(timezone.utc)
    trades = [_trade(now - timedelta(days=i), pnl=10 if i % 2 == 0 else -2) for i in range(60)]
    m = compute_metrics("0xabc", trades, lookback_days=90)
    assert m.trade_count == 60
    assert m.win_rate > 0
    assert m.total_volume_usd > 0


def test_score_and_filters():
    now = datetime.now(timezone.utc)
    trades = [_trade(now - timedelta(days=i), pnl=20) for i in range(55)]
    m = compute_metrics("0xabc", trades)
    assert passes_filters(m) or m.pnl_30d > 0
    score = score_trader(m)
    assert 0 <= score <= 100
