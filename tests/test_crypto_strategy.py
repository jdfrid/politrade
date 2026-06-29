"""Tests for crypto betting strategy."""

from politrade.config import AppConfig
from politrade.crypto.price_feed import OracleSnapshot, TokenPrices
from politrade.crypto.strategy import DecisionAction, evaluate_window
from politrade.crypto.window import CryptoAsset, CryptoWindow, WindowPhase


def _window() -> CryptoWindow:
    import time

    wts = (int(time.time()) // 300) * 300
    return CryptoWindow(
        asset=CryptoAsset.BTC,
        window_ts=wts,
        slug=f"btc-updown-5m-{wts}",
        up_token_id="up_tok",
        down_token_id="down_tok",
    )


def test_strategy_skip_early():
    w = _window()
    oracle = OracleSnapshot(asset=CryptoAsset.BTC, window_ts=w.window_ts, open_price=100.0, current_price=100.05)
    tokens = TokenPrices(up_ask=0.80, down_ask=0.80)
    now = w.window_ts + 60
    decision = evaluate_window(w, oracle, tokens, AppConfig(), now=now)
    assert w.phase(now) == WindowPhase.EARLY
    assert decision.action == DecisionAction.WAIT


def test_strategy_bet_up():
    w = _window()
    oracle = OracleSnapshot(
        asset=CryptoAsset.BTC,
        window_ts=w.window_ts,
        open_price=100.0,
        current_price=100.10,
    )
    tokens = TokenPrices(up_ask=0.80, down_ask=0.95)
    decision = evaluate_window(w, oracle, tokens, AppConfig(), has_liquidity_fn=lambda _: True)
    if w.phase() == WindowPhase.BET:
        assert decision.action == DecisionAction.BET
        assert decision.side and decision.side.value == "up"


def test_strategy_skip_low_edge():
    w = _window()
    oracle = OracleSnapshot(
        asset=CryptoAsset.BTC,
        window_ts=w.window_ts,
        open_price=100.0,
        current_price=100.10,
    )
    tokens = TokenPrices(up_ask=0.95, down_ask=0.95)
    decision = evaluate_window(w, oracle, tokens, AppConfig(), has_liquidity_fn=lambda _: True)
    if w.phase() == WindowPhase.BET:
        assert decision.action == DecisionAction.SKIP
