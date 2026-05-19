"""Tests for SQLite repository."""

from politrade.config import AppConfig
from politrade.storage.repository import Repository


def test_upsert_and_leaders(monkeypatch, tmp_path):
    db_path = tmp_path / "test.db"
    config = AppConfig()
    monkeypatch.setattr(
        config.env,
        "database_url",
        f"sqlite:///{db_path}",
    )
    repo = Repository(config)
    repo.upsert_trader("0xABC", username="trader1", score=80.0, is_active_leader=True)
    leaders = repo.get_active_leaders()
    assert len(leaders) == 1
    assert leaders[0].address == "0xabc"
