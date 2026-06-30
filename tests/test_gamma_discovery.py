"""Tests for Gamma 5M discovery."""

from politrade.crypto.gamma_discovery import parse_event_to_window, split_current_and_upcoming
from politrade.crypto.window import CryptoAsset, compute_window_ts, parse_slug_parts


def test_parse_slug_parts():
    assert parse_slug_parts("btc-updown-5m-1778448000") == ("btc", 1778448000)
    assert parse_slug_parts("doge-updown-5m-123") == ("doge", 123)
    assert parse_slug_parts("invalid") is None


def test_parse_event_to_window():
    event = {
        "slug": "eth-updown-5m-1778448000",
        "title": "Ethereum Up or Down",
        "active": True,
        "closed": False,
        "markets": [{
            "conditionId": "0xabc",
            "question": "ETH Up or Down - 5 min",
            "clobTokenIds": ["up_tok", "down_tok"],
            "closed": False,
            "active": True,
        }],
    }
    w = parse_event_to_window(event)
    assert w is not None
    assert w.asset == CryptoAsset.ETH
    assert w.window_ts == 1778448000
    assert w.up_token_id == "up_tok"
    assert w.down_token_id == "down_tok"


def test_split_current_and_upcoming():
    from politrade.crypto.window import CryptoWindow

    now_wts = compute_window_ts(1778448123)
    current = CryptoWindow(
        asset=CryptoAsset.BTC, window_ts=now_wts, slug=f"btc-updown-5m-{now_wts}",
        up_token_id="u", down_token_id="d",
    )
    future = CryptoWindow(
        asset=CryptoAsset.ETH, window_ts=now_wts + 300, slug=f"eth-updown-5m-{now_wts + 300}",
        up_token_id="u", down_token_id="d",
    )
    cur, up = split_current_and_upcoming([future, current], now=1778448123)
    assert len(cur) == 1
    assert cur[0].asset == CryptoAsset.BTC
    assert len(up) == 1
    assert up[0].asset == CryptoAsset.ETH
