"""Tests for live system status."""

from unittest.mock import MagicMock, patch

from politrade.config import AppConfig
from politrade.web.system_status import build_live_status


def test_build_live_status_shape():
    cfg = AppConfig()
    mock_repo = MagicMock()
    mock_repo.get_state.return_value = None
    mock_repo.list_audit_logs.return_value = []
    mock_repo.crypto_bets_summary.return_value = {
        "total": 0, "resolved": 0, "wins": 0, "losses": 0, "total_pnl": 0,
    }

    with (
        patch("politrade.web.system_status.Repository", return_value=mock_repo),
        patch("politrade.web.system_status.DataClient") as data_cls,
        patch("politrade.web.system_status.ClobClientWrapper") as clob_cls,
        patch("politrade.web.system_status.wallet_status") as wallet_status,
        patch("politrade.web.system_status._cached_wallet_activity") as activity_fn,
        patch("politrade.web.system_status.get_position_monitor") as mon,
        patch("politrade.web.system_status.get_crypto_runner") as crypto_runner,
        patch("politrade.web.system_status.get_price_feed") as feed,
        patch("politrade.web.system_status.RiskManager") as risk_cls,
    ):
        data = data_cls.return_value
        data.get_leaderboard.return_value = []
        clob = clob_cls.return_value
        clob.is_configured = False
        wallet_status.return_value = {
            "configured": False,
            "funder_address": "",
            "funder_short": "—",
            "errors": [],
        }
        activity_fn.return_value = MagicMock(
            configured=False,
            cash_usd=None,
            total_value_usd=0,
            total_pnl_usd=0,
            positions_count=0,
            open_orders_count=0,
        )
        mon.return_value.status = {"running": True, "ticks": 5}
        crypto_runner.return_value.status = {"running": True, "auto_bet": True}
        feed.return_value.status.return_value = {"ws_running": False}
        risk_cls.return_value.is_kill_switch_active.return_value = False

        out = build_live_status(cfg)

    assert "updated_at" in out
    assert out["connections"]["database"] == "ok"
    assert out["connections"]["data_api"] == "ok"
    assert out["connections"]["clob"] == "off"
    assert out["wallet"]["label"] == "לא מחובר"
    assert out["trades"]["crypto_wins"] == 0
