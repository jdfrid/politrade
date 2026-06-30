"""Tests for crypto window discovery."""

from unittest.mock import patch

from politrade.crypto.discovery import discover_windows
from politrade.crypto.window import CryptoAsset, CryptoWindow


def test_discover_windows_mock():
    now_wts = 1778448000
    mock_window = CryptoWindow(
        asset=CryptoAsset.BTC,
        window_ts=now_wts,
        slug="btc-updown-5m-1778448000",
        up_token_id="up",
        down_token_id="down",
    )
    mock_upcoming = CryptoWindow(
        asset=CryptoAsset.ETH,
        window_ts=now_wts + 300,
        slug="eth-updown-5m-1778448300",
        up_token_id="up",
        down_token_id="down",
    )

    with patch("politrade.crypto.discovery.discover_5m_windows_from_gamma") as fetch:
        fetch.return_value = [mock_window, mock_upcoming]
        with patch("politrade.crypto.discovery.split_current_and_upcoming") as split:
            split.return_value = ([mock_window], [mock_upcoming])
            result = discover_windows(upcoming_count=1)

    assert len(result.current) == 1
    assert result.current[0].window.asset == CryptoAsset.BTC
    assert result.current[0].tradable is True
    assert len(result.upcoming) == 1
