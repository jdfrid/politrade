"""Tests for evolution-based simulation learner."""

from politrade.crypto.learner import _crypto_user_params


def test_default_params_no_fixed_rules(tmp_path, monkeypatch):
    db = tmp_path / "learner.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db}")
    from politrade.storage.repository import Repository

    params = _crypto_user_params(Repository())
    assert params["crypto_min_edge_pct"] == 0
    assert params["crypto_no_bet_first_seconds"] == 0
    assert params["crypto_min_move_pct"] == 0
