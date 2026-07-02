"""Tests for live dashboard API."""

from politrade.config import AppConfig
from politrade.crypto.live_dashboard import build_live_dashboard
from politrade.storage.repository import Repository


def test_build_live_dashboard_structure(monkeypatch, tmp_path):
    db_path = tmp_path / "live_dash.db"
    config = AppConfig()
    monkeypatch.setattr(config.env, "database_url", f"sqlite:///{db_path}")
    Repository(config)

    data = build_live_dashboard(config)
    assert "opportunities" in data
    assert "recent_bets" in data
    assert "settings" in data
    assert "updated_at" in data
    assert isinstance(data["opportunities"], list)
