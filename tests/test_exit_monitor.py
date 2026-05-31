"""Tests for ExitMonitor with percentage-based targets."""

from datetime import datetime, timezone
from unittest.mock import MagicMock

from politrade.config import AppConfig
from politrade.execution.exit_monitor import ExitMonitor
from politrade.storage.models import Position
from politrade.storage.repository import Repository


def _open_position(monkeypatch, tmp_path) -> tuple[AppConfig, Repository, Position]:
    db_path = tmp_path / "exit.db"
    config = AppConfig()
    monkeypatch.setattr(config, "exit", {
        "take_profit_pct": 50,
        "stop_loss_pct": 30,
        "max_hold_days": 30,
        "monitor_seconds": 20,
    })
    monkeypatch.setattr(config.env, "database_url", f"sqlite:///{db_path}")
    repo = Repository(config)
    pos = repo.create_position(
        token_id="tok1",
        market_id="mkt1",
        leader_address="0xleader",
        leader_trade_id="t1",
        entry_price=0.5,
        entry_cost_usd=50.0,
        shares=100.0,
        market_title="Test Market",
    )
    return config, repo, pos


def test_exit_monitor_sells_on_take_profit(monkeypatch, tmp_path):
    config, repo, pos = _open_position(monkeypatch, tmp_path)

    clob = MagicMock()
    clob.is_configured = True
    clob.market_sell.return_value = {"ok": True}
    clob.cancel_orders_for_token.return_value = None

    mon = ExitMonitor(config, repo, clob=clob)
    reason = mon.check_position(pos, dry_run=False, price=0.8)

    assert reason == "take_profit"
    clob.market_sell.assert_called_once()
    closed = repo.list_closed_positions(limit=1)[0]
    assert closed.status == "closed"
    assert closed.exit_reason == "take_profit"


def test_exit_monitor_dry_run_no_sell(monkeypatch, tmp_path):
    config, repo, pos = _open_position(monkeypatch, tmp_path)
    clob = MagicMock()
    clob.is_configured = True

    mon = ExitMonitor(config, repo, clob=clob, notifier=MagicMock())
    reason = mon.check_position(pos, dry_run=True, price=0.8)

    assert reason == "take_profit"
    clob.market_sell.assert_not_called()
    assert repo.count_open_positions() == 1
