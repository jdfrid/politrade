"""Tests for wallet activity parsing."""

from politrade.web.wallet_activity import _items_from_polymarket_trades, _items_from_audit


def test_polymarket_trade_item():
    trades = [
        {
            "side": "BUY",
            "title": "Will X happen?",
            "outcome": "Yes",
            "price": 0.55,
            "usdcSize": 10,
            "timestamp": 1700000000,
            "transactionHash": "0xabc",
        }
    ]
    items = _items_from_polymarket_trades(trades)
    assert len(items) == 1
    assert items[0].status == "success"
    assert items[0].source == "polymarket"
    assert items[0].amount_usd == 10.0


def test_audit_failure_item():
    class Row:
        event = "manual_execute_failed"
        level = "error"
        message = "geoblock"
        created_at = None

    items = _items_from_audit([Row()])
    assert len(items) == 1
    assert items[0].status == "failed"
    assert items[0].status_label == "נכשל"
