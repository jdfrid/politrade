"""Tests for crypto window timing."""

import time

from politrade.crypto.window import (
    CryptoAsset,
    WindowPhase,
    build_slug,
    compute_window_ts,
    parse_token_ids,
    parse_market,
)


def test_compute_window_ts():
    ts = 1778448123
    assert compute_window_ts(ts) == 1778448000


def test_build_slug():
    assert build_slug(CryptoAsset.BTC, 1778448000) == "btc-updown-5m-1778448000"
    assert build_slug(CryptoAsset.DOGE, 100) == "doge-updown-5m-100"


def test_parse_slug_parts():
    from politrade.crypto.window import parse_slug_parts, resolve_asset

    assert parse_slug_parts("bnb-updown-5m-999") == ("bnb", 999)
    assert resolve_asset("hype") == CryptoAsset.HYPE


def test_window_phase_bet():
    from politrade.crypto.window import CryptoWindow, reset_phase_cfg_cache

    reset_phase_cfg_cache()
    w = CryptoWindow(asset=CryptoAsset.BTC, window_ts=1000, slug="btc-updown-5m-1000")
    assert w.phase(1000 + 150) == WindowPhase.BET
    assert w.phase(1000 + 60) == WindowPhase.EARLY
    assert w.phase(1000 + 260) == WindowPhase.LATE
    assert w.phase(1000 + 300) == WindowPhase.CLOSED


def test_parse_token_ids():
    market = {"clobTokenIds": '["tok_up", "tok_down"]'}
    pair = parse_token_ids(market)
    assert pair is not None
    assert pair.up_token_id == "tok_up"
    assert pair.down_token_id == "tok_down"


def test_parse_market():
    market = {
        "conditionId": "0xabc",
        "question": "BTC Up or Down",
        "clobTokenIds": ["up1", "down1"],
        "closed": False,
        "active": True,
    }
    w = parse_market(CryptoAsset.BTC, 1778448000, market)
    assert w is not None
    assert w.up_token_id == "up1"
    assert w.condition_id == "0xabc"
