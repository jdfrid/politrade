"""Tests for crypto wallet budget cap."""

from politrade.config import AppConfig
from politrade.crypto.budget import cap_bet_for_budget
from politrade.storage.repository import Repository


def test_cap_bet_blocks_when_budget_full(monkeypatch, tmp_path):
    db_path = tmp_path / "budget.db"
    config = AppConfig()
    monkeypatch.setattr(config.env, "database_url", f"sqlite:///{db_path}")
    repo = Repository(config)
    cfg = {"max_wallet_usd": 30, "bet_usd": 5}

    repo.create_crypto_bet(
        asset="btc",
        window_ts=100,
        slug="btc-test",
        side="up",
        token_id="t1",
        condition_id="c1",
        open_oracle_price=50000.0,
        entry_price=0.5,
        bet_usd=30,
        shares=60,
        status="open",
    )

    amount, reason = cap_bet_for_budget(5, cfg, repo, live=True)
    assert amount == 0.0
    assert reason is not None


def test_cap_bet_trims_to_remaining_room(monkeypatch, tmp_path):
    db_path = tmp_path / "budget2.db"
    config = AppConfig()
    monkeypatch.setattr(config.env, "database_url", f"sqlite:///{db_path}")
    repo = Repository(config)
    cfg = {"max_wallet_usd": 30, "bet_usd": 5}

    repo.create_crypto_bet(
        asset="btc",
        window_ts=100,
        slug="btc-test",
        side="up",
        token_id="t1",
        condition_id="c1",
        open_oracle_price=50000.0,
        entry_price=0.5,
        bet_usd=27,
        shares=54,
        status="open",
    )

    amount, reason = cap_bet_for_budget(5, cfg, repo, live=True)
    assert amount == 3.0
    assert reason is None


def test_cap_bet_unlimited_when_zero(monkeypatch, tmp_path):
    db_path = tmp_path / "budget3.db"
    config = AppConfig()
    monkeypatch.setattr(config.env, "database_url", f"sqlite:///{db_path}")
    repo = Repository(config)
    cfg = {"max_wallet_usd": 0, "bet_usd": 5}

    amount, reason = cap_bet_for_budget(5, cfg, repo, live=True)
    assert amount == 5.0
    assert reason is None
