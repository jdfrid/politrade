"""Tests that simulation actually places virtual bets."""

from unittest.mock import MagicMock, patch

from politrade.crypto.price_feed import OracleSnapshot, TokenPrices, synthetic_token_prices, token_prices_for_sim
from politrade.crypto.strategy import DecisionAction, evaluate_window
from politrade.config import AppConfig
from politrade.crypto.window import CryptoAsset, CryptoWindow


def test_synthetic_prices_enable_bet_without_clob():
    window = CryptoWindow(
        asset=CryptoAsset.BTC,
        window_ts=1000,
        slug="btc-updown-5m-1000",
        up_token_id="up",
        down_token_id="down",
    )
    oracle = OracleSnapshot(CryptoAsset.BTC, 1000, open_price=100.0, current_price=100.15)
    tokens = synthetic_token_prices(oracle)
    assert tokens.up_ask is not None
    assert tokens.down_ask is not None

    d = evaluate_window(
        window, oracle, tokens, AppConfig(),
        cfg_override={"no_bet_first_seconds": 0, "min_edge_pct": 0, "bet_usd": 5},
        now=1030,
    )
    assert d.action == DecisionAction.BET


def test_token_prices_for_sim_fills_missing_clob():
    oracle = OracleSnapshot(CryptoAsset.BTC, 1000, open_price=100.0, current_price=99.9)
    window = CryptoWindow(
        asset=CryptoAsset.BTC,
        window_ts=1000,
        slug="btc-updown-5m-1000",
        up_token_id="up",
        down_token_id="down",
    )
    clob = MagicMock()
    clob.is_configured = False
    prices = token_prices_for_sim(clob, window, oracle)
    assert prices.up_ask is not None
    assert prices.down_ask is not None


def test_sim_runner_places_bet_on_tick(tmp_path, monkeypatch):
    db = tmp_path / "bet.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db}")

    window_ts = 1778448000
    tick_now = window_ts + 45

    window = CryptoWindow(
        asset=CryptoAsset.BTC,
        window_ts=window_ts,
        slug="btc-updown-5m-1778448000",
        up_token_id="up",
        down_token_id="down",
    )

    from politrade.crypto.sim_runner import SimRunner
    from politrade.storage.repository import Repository

    runner = SimRunner()
    repo = Repository()
    repo.reset_sim_ledger(1000.0)
    from politrade.crypto.sim_optimizer import ensure_population
    ensure_population(repo, 1000.0)
    runner.set_auto_sim(True)

    with patch("politrade.crypto.sim_runner.time.time", return_value=float(tick_now)):
        with patch.object(runner, "_get_config") as gc:
            gc.return_value = AppConfig()
            with patch("politrade.crypto.sim_runner.compute_window_ts", return_value=window_ts):
                with patch("politrade.crypto.sim_runner.discover_5m_windows_from_gamma", return_value=[window]):
                    with patch("politrade.crypto.sim_runner.get_price_feed") as gf:
                        feed = MagicMock()
                        feed.get_snapshot.return_value = OracleSnapshot(
                            CryptoAsset.BTC, window_ts, open_price=100.0, current_price=100.2,
                        )
                        gf.return_value = feed
                        with patch("politrade.crypto.sim_runner.token_prices_for_sim") as tp:
                            tp.return_value = TokenPrices(up_ask=0.55, down_ask=0.48)
                            with patch("politrade.crypto.sim_runner.ClobClientWrapper") as clob_cls:
                                clob_cls.return_value.is_configured = False
                                runner.tick_once()

    assert repo.list_sim_bets(limit=10), "expected champion sim bet"
    assert repo.get_variant_bets_for_window(window_ts), "expected variant bets"
