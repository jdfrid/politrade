"""Tests for sim runner tick (mocked)."""

from unittest.mock import MagicMock, patch

from politrade.crypto.sim_runner import SimRunner
from politrade.crypto.window import CryptoAsset, CryptoWindow


def test_sim_runner_tick_once_mock(tmp_path, monkeypatch):
    db = tmp_path / "sim.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db}")

    window = CryptoWindow(
        asset=CryptoAsset.BTC,
        window_ts=1778448000,
        slug="btc-updown-5m-1778448000",
        up_token_id="up",
        down_token_id="down",
    )

    runner = SimRunner()
    with patch.object(runner, "_get_config") as gc:
        from politrade.config import AppConfig

        gc.return_value = AppConfig()
        with patch("politrade.crypto.sim_runner.discover_5m_windows_from_gamma", return_value=[window]):
            with patch("politrade.crypto.sim_runner.get_price_feed") as gf:
                feed = MagicMock()
                feed.get_snapshot.return_value = MagicMock(
                    to_dict=lambda: {},
                    delta_pct=0.1,
                    open_price=100.0,
                )
                gf.return_value = feed
                with patch("politrade.crypto.sim_runner.fetch_token_prices"):
                    with patch("politrade.crypto.sim_runner.evaluate_window") as ev:
                        from politrade.crypto.strategy import DecisionAction, StrategyDecision

                        ev.return_value = StrategyDecision(
                            action=DecisionAction.WAIT,
                            reason="test wait",
                        )
                        runner.tick_once()

    state = runner.get_live_state()
    assert state["markets"]
