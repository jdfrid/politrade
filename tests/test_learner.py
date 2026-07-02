"""Tests for evolution-based simulation learner."""

from politrade.crypto.learner import _crypto_user_params, run_learner_after_cycle
from politrade.crypto.sim_mode import set_auto_learn
from politrade.web.user_settings import load_user_settings, save_user_settings


def test_default_params_no_fixed_rules(tmp_path, monkeypatch):
    db = tmp_path / "learner.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db}")
    from politrade.storage.repository import Repository

    params = _crypto_user_params(Repository())
    assert params["crypto_min_edge_pct"] == 0
    assert params["crypto_no_bet_first_seconds"] == 0
    assert params["crypto_min_move_pct"] == 0


def test_learner_does_not_overwrite_dashboard_settings(tmp_path, monkeypatch):
    db = tmp_path / "learner2.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db}")
    from politrade.config import AppConfig
    from politrade.storage.repository import Repository

    config = AppConfig()
    monkeypatch.setattr(config.env, "database_url", f"sqlite:///{db}")
    repo = Repository(config)
    save_user_settings(repo, {"crypto_bet_usd": 5, "crypto_min_edge_pct": 15})
    set_auto_learn(repo, True)
    repo.create_sim_variant(
        label="champ",
        params_json='{"bet_usd":3,"min_edge_pct":0,"strategy_mode":"follow_oracle"}',
        param_hash="abc123unique",
        start_balance=1000,
        is_champion=True,
    )
    cycle = repo.create_sim_cycle(window_ts=1700000000, lessons_he="test")

    saved: list[dict] = []
    real_save = save_user_settings

    def track_save(r, data):
        saved.append(data)
        return real_save(r, data)

    monkeypatch.setattr("politrade.crypto.learner.save_user_settings", track_save)
    run_learner_after_cycle(cycle, config, repo)

    assert saved == []
    s = load_user_settings(repo)
    assert s["crypto_bet_usd"] == 5
    assert s["crypto_min_edge_pct"] == 15
