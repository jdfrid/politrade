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


def test_crypto_bets_schema_migration(monkeypatch, tmp_path):
    """Legacy DB missing columns on crypto_bets should migrate cleanly."""
    db_path = tmp_path / "legacy.db"
    config = AppConfig()
    monkeypatch.setattr(config.env, "database_url", f"sqlite:///{db_path}")

    from sqlalchemy import create_engine, text

    engine = create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE crypto_bets ("
                "id INTEGER PRIMARY KEY, asset VARCHAR(8), window_ts INTEGER, "
                "slug VARCHAR(128), side VARCHAR(8), token_id VARCHAR(128), "
                "entry_price FLOAT, bet_usd FLOAT, shares FLOAT, status VARCHAR(16)"
                ")"
            )
        )
    engine.dispose()

    repo = Repository(config)
    bets = repo.list_crypto_bets(10)
    assert bets == []

    insp_cols = {c["name"] for c in __import__("sqlalchemy").inspect(repo.engine).get_columns("crypto_bets")}
    assert "market_title" in insp_cols
    assert "edge_pct" in insp_cols
