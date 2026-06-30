"""Tests for simulation engine."""

from politrade.crypto.sim_engine import execute_sim_bet
from politrade.crypto.strategy import DecisionAction, StrategyDecision
from politrade.crypto.window import CryptoAsset, CryptoWindow
from politrade.storage.repository import Repository


def test_execute_sim_bet_debits_balance(tmp_path, monkeypatch):
    db = tmp_path / "test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db}")
    from politrade.config import AppConfig

    cfg = AppConfig()
    repo = Repository(cfg)
    repo.reset_sim_ledger(100.0)

    window = CryptoWindow(
        asset=CryptoAsset.BTC,
        window_ts=1778448000,
        slug="btc-updown-5m-1778448000",
        up_token_id="up",
        down_token_id="down",
    )
    decision = StrategyDecision(
        action=DecisionAction.BET,
        side=__import__("politrade.crypto.window", fromlist=["BetSide"]).BetSide.UP,
        token_id="up",
        entry_ask=0.45,
        edge_pct=20,
        reason="test",
    )
    bet = execute_sim_bet(repo, window, decision, bet_usd=10, open_oracle_price=50000)
    assert bet is not None
    assert repo.get_sim_balance() == 90.0
    assert repo.has_sim_bet_for_window("btc", 1778448000)


def test_resolve_sim_bet_win_pnl(tmp_path, monkeypatch):
    from politrade.crypto.sim_engine import _resolve_one_bet
    from politrade.storage.models import SimBet

    bet = SimBet(
        id=1,
        asset="btc",
        window_ts=1778448000,
        slug="btc-updown-5m-1778448000",
        side="up",
        token_id="up",
        open_oracle_price=100.0,
        entry_price=0.5,
        bet_usd=10.0,
        shares=20.0,
        status="open",
    )

    class FakeFeed:
        def get_snapshot(self, window):
            from politrade.crypto.price_feed import OracleSnapshot

            return OracleSnapshot(asset=window.asset, window_ts=window.window_ts, close_price=101.0)

        def set_close_price(self, *a, **k):
            pass

    class FakeRepo:
        def resolve_sim_bet(self, bet_id, **kwargs):
            bet.status = "won" if kwargs["won"] else "lost"
            bet.realized_pnl = kwargs["realized_pnl"]

        def audit(self, *a, **k):
            pass

    result = _resolve_one_bet(bet, FakeFeed(), FakeRepo())
    assert result is not None
    won, pnl = result
    assert won is True
    assert pnl == 10.0
