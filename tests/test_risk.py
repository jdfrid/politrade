"""Tests for risk manager."""

from datetime import datetime, timezone

from politrade.config import AppConfig
from politrade.execution.risk import RiskManager
from politrade.signals.trade_selector import CopySignal
from politrade.storage.repository import Repository


def test_kill_switch_file(tmp_path, monkeypatch):
    stop_file = tmp_path / "STOP_TRADING"
    stop_file.touch()
    config = AppConfig()
    monkeypatch.setattr(
        AppConfig,
        "kill_switch_path",
        property(lambda self: stop_file),
    )
    risk = RiskManager(config, Repository(config))
    signal = CopySignal(
        leader_address="0x1",
        market_id="m1",
        token_id="t1",
        side="BUY",
        leader_price=0.5,
        leader_size_usd=100,
        leader_trade_id="tid1",
        detected_at=datetime.now(timezone.utc),
    )
    decision = risk.evaluate(signal)
    assert not decision.approved
    assert decision.reason == "kill_switch_active"


def test_position_sizing():
    config = AppConfig()
    risk = RiskManager(config, Repository(config))
    signal = CopySignal(
        leader_address="0x1",
        market_id="m1",
        token_id="t1",
        side="BUY",
        leader_price=0.5,
        leader_size_usd=1000,
        leader_trade_id="tid2",
        detected_at=datetime.now(timezone.utc),
    )
    decision = risk.evaluate(signal)
    max_pos = float(config.risk.get("max_position_usd", 50))
    if decision.approved:
        assert decision.position_size_usd <= max_pos
