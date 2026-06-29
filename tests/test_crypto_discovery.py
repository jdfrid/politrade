"""Tests for crypto window discovery."""

from unittest.mock import MagicMock, patch

from politrade.crypto.discovery import discover_windows
from politrade.crypto.window import CryptoAsset, CryptoWindow


def test_discover_windows_mock():
    mock_window = CryptoWindow(
        asset=CryptoAsset.BTC,
        window_ts=1778448000,
        slug="btc-updown-5m-1778448000",
        up_token_id="up",
        down_token_id="down",
    )

    with patch("politrade.crypto.discovery.fetch_window_market") as fetch:
        fetch.return_value = mock_window
        with patch("politrade.crypto.discovery.enabled_assets", return_value=[CryptoAsset.BTC]):
            with patch("politrade.crypto.discovery.compute_window_ts", return_value=1778448000):
                result = discover_windows(upcoming_count=1)

    assert len(result.current) == 1
    assert result.current[0].window.asset == CryptoAsset.BTC
    assert result.current[0].tradable is True
    assert len(result.upcoming) == 1
