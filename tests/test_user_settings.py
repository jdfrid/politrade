"""Tests for dashboard settings persistence."""

from politrade.web.user_settings import load_user_settings, save_user_settings


def test_save_user_settings_merges_existing(tmp_path, monkeypatch):
    db = tmp_path / "settings.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db}")
    from politrade.storage.repository import Repository

    repo = Repository()
    save_user_settings(repo, {"crypto_min_edge_pct": 15, "crypto_bet_usd": 5})
    save_user_settings(repo, {"crypto_bet_usd": 7})

    s = load_user_settings(repo)
    assert s["crypto_bet_usd"] == 7
    assert s["crypto_min_edge_pct"] == 15


def test_save_user_settings_uncheck_auto_learn(tmp_path, monkeypatch):
    db = tmp_path / "settings2.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db}")
    from politrade.storage.repository import Repository

    repo = Repository()
    save_user_settings(repo, {"sim_auto_learn": True, "crypto_auto_bet": True})
    save_user_settings(repo, {"sim_auto_learn": "0", "crypto_auto_bet": "0"})

    s = load_user_settings(repo)
    assert s["sim_auto_learn"] is False
    assert s["crypto_auto_bet"] is False
