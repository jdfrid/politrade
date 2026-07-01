"""Tests for sim bet display helpers."""

from datetime import datetime, timezone

from politrade.crypto.sim_display import (
    bet_status_display,
    enrich_sim_bet_dict,
    format_window_period_he,
    resolve_market_title,
)
from politrade.storage.models import SimBet


def test_bet_status_hebrew():
    assert bet_status_display("won")["status_label_he"] == "הצלחה"
    assert bet_status_display("lost")["status_class"] == "err"
    assert bet_status_display("lost")["status_label_he"] == "כשלון"


def test_format_window_period():
    s = format_window_period_he(1778448000)
    assert "UTC" in s
    assert "–" in s


def test_enrich_sim_bet_dict_uses_title():
    bet = SimBet(
        id=1,
        asset="btc",
        window_ts=1778448000,
        slug="btc-updown-5m-1778448000",
        market_title="Bitcoin Up or Down - March 10, 3:00AM-3:05AM ET",
        side="up",
        token_id="up",
        entry_price=0.55,
        bet_usd=5,
        shares=9,
        status="lost",
        realized_pnl=-5.0,
        created_at=datetime(2026, 3, 10, 15, 1, 0, tzinfo=timezone.utc),
    )
    d = enrich_sim_bet_dict(bet)
    assert "Bitcoin Up or Down" in d["market_title"]
    assert d["status_label_he"] == "כשלון"
    assert d["status_class"] == "err"
    assert d["window_period_he"]


def test_resolve_market_title_fallback():
    t = resolve_market_title(market_title=None, asset="eth", slug="eth-updown-5m-1", window_ts=1778448000)
    assert "ETH" in t
