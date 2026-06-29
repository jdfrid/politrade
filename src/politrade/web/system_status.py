"""Live system status for the status bar."""

from __future__ import annotations

from datetime import datetime, timezone

from politrade.api.clob_client import ClobClientWrapper
from politrade.api.data_client import DataClient
from politrade.crypto.runner import get_crypto_runner
from politrade.crypto.price_feed import get_price_feed
from politrade.config import AppConfig
from politrade.execution.position_monitor import get_position_monitor
from politrade.execution.risk import RiskManager
from politrade.storage.repository import Repository
from politrade.wallet_store import wallet_status
from politrade.web.user_settings import get_effective_config

FAIL_EVENTS = frozenset(
    {"manual_execute_failed", "execute_failed", "exit_failed", "crypto_bet_failed"}
)


def build_live_status(config: AppConfig | None = None) -> dict:
    cfg = config or get_effective_config()
    repo = Repository(cfg)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    # Database
    db_ok = True
    try:
        repo.get_state("health_check")
    except Exception:
        db_ok = False

    # Data API
    data_ok = False
    data_err = ""
    data = DataClient(cfg)
    try:
        data.get_leaderboard(limit=1)
        data_ok = True
    except Exception as exc:
        data_err = str(exc)[:80]
    finally:
        data.close()

    # CLOB / wallet
    wallet = wallet_status(cfg)
    clob = ClobClientWrapper(cfg)
    clob_ok = False
    clob_err = ""
    cash: float | None = None
    open_orders = 0
    if clob.is_configured:
        try:
            client = clob._ensure_client()
            client.get_ok()
            clob_ok = True
            details = clob.get_balance_details()
            cash = details.get("balance")
            open_orders = clob.count_open_orders()
        except Exception as exc:
            clob_err = str(exc)[:80]
    elif wallet.get("funder_address"):
        clob_err = "ארנק לא מלא — הגדר Funder + Private Key"

    mon = get_position_monitor().status
    crypto = get_crypto_runner().status
    feed = get_price_feed().status()
    risk = RiskManager(cfg, repo)
    crypto_summary = repo.crypto_bets_summary()

    last_fail = ""
    for row in repo.list_audit_logs(30):
        if row.level == "error" and row.event in FAIL_EVENTS:
            last_fail = row.message[:100]
            break

    conn_clob = "ok" if clob_ok else ("off" if not wallet["configured"] else "err")

    return {
        "updated_at": now,
        "connections": {
            "database": "ok" if db_ok else "err",
            "data_api": "ok" if data_ok else "err",
            "data_api_error": data_err,
            "clob": conn_clob,
            "clob_error": clob_err,
            "position_monitor": "ok" if mon.get("running") else "err",
            "monitor_ticks": mon.get("ticks", 0),
            "crypto_runner": "ok" if crypto.get("running") else "err",
            "chainlink_ws": "ok" if feed.get("ws_running") else "err",
        },
        "wallet": {
            "configured": wallet["configured"],
            "label": "מחובר" if wallet["configured"] else "לא מחובר",
            "funder_short": wallet.get("funder_short") or "—",
            "cash_usd": cash,
            "errors": wallet.get("errors") or [],
        },
        "trades": {
            "open_positions": crypto_summary.get("total", 0) - crypto_summary.get("resolved", 0),
            "live_pnl_usd": crypto_summary.get("total_pnl", 0),
            "live_value_usd": 0,
            "open_orders": open_orders,
            "bot_running": crypto.get("running", False),
            "bot_mode": "crypto_auto" if crypto.get("auto_bet") else "crypto_manual",
            "kill_switch": risk.is_kill_switch_active(),
            "last_failure": last_fail,
            "crypto_wins": crypto_summary.get("wins", 0),
            "crypto_losses": crypto_summary.get("losses", 0),
        },
    }
