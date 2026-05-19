"""Tests for trade signal selection."""

from datetime import datetime, timezone

from politrade.config import AppConfig
from politrade.signals.trade_selector import TradeSelector
from politrade.storage.repository import Repository


def test_rejects_sell_side(monkeypatch, tmp_path):
    db_path = tmp_path / "test.db"
    config = AppConfig()
    monkeypatch.setattr(config.env, "database_url", f"sqlite:///{db_path}")
    repo = Repository(config)
    repo.upsert_trader("0xleader", score=85.0, is_active_leader=True)

    selector = TradeSelector(config, repo)
    trade = {
        "side": "SELL",
        "asset": "token1",
        "conditionId": "market1",
        "usdcSize": 50,
        "price": 0.6,
        "id": "t1",
        "proxyWallet": "0xleader",
    }
    assert selector.evaluate(trade, 85.0) is None


def test_accepts_buy_signal(monkeypatch, tmp_path):
    db_path = tmp_path / "test.db"
    config = AppConfig()
    monkeypatch.setattr(config.env, "database_url", f"sqlite:///{db_path}")
    repo = Repository(config)

    class FakeClob:
        is_configured = False

    selector = TradeSelector(config, repo, clob=FakeClob())  # type: ignore
    trade = {
        "side": "BUY",
        "asset": "token1",
        "conditionId": "market1",
        "usdcSize": 50,
        "price": 0.6,
        "id": "t2",
        "proxyWallet": "0xleader",
    }
    signal = selector.evaluate(trade, 85.0)
    assert signal is not None
    assert signal.side == "BUY"
    assert signal.leader_size_usd == 50
