"""Fetch and merge Polymarket wallet activity for the dashboard."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from politrade.api.clob_client import ClobClientWrapper
from politrade.api.data_client import DataClient
from politrade.config import AppConfig
from politrade.logging_setup import get_logger
from politrade.storage.repository import Repository

log = get_logger(__name__)

FAILED_EVENTS = frozenset(
    {"manual_execute_failed", "execute_failed", "exit_failed", "manual_copy"}
)


@dataclass
class WalletActivityItem:
    at: str
    source: str
    source_label: str
    side: str
    title: str
    outcome: str
    amount_usd: float
    price: float
    status: str
    status_label: str
    detail: str = ""
    trade_id: str = ""


@dataclass
class WalletActivitySummary:
    configured: bool
    funder_address: str
    cash_usd: float | None
    portfolio_usd: float
    positions_count: int
    open_orders_count: int
    trades_count: int
    failed_count: int
    error: str | None = None
    items: list[WalletActivityItem] = field(default_factory=list)


def _parse_ts(raw: Any) -> datetime | None:
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        ts = float(raw)
        if ts > 1e12:
            ts /= 1000.0
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    s = str(raw).strip()
    if not s:
        return None
    try:
        if s.isdigit():
            ts = float(s)
            if ts > 1e12:
                ts /= 1000.0
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, OSError, OverflowError):
        return None


def _fmt_ts(dt: datetime | None) -> str:
    if dt is None:
        return "—"
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M")


def _trade_usd(trade: dict[str, Any]) -> float:
    for key in ("usdcSize", "usdc_size", "size", "amount"):
        val = trade.get(key)
        if val is not None:
            try:
                return abs(float(val))
            except (TypeError, ValueError):
                pass
    price = float(trade.get("price", 0) or 0)
    size = float(trade.get("size", 0) or 0)
    return abs(price * size)


def _trade_title(trade: dict[str, Any]) -> str:
    for key in ("title", "question", "marketTitle", "name"):
        val = trade.get(key)
        if val:
            return str(val)[:120]
    return str(trade.get("market", trade.get("conditionId", "—")))[:120]


def _items_from_polymarket_trades(trades: list[dict[str, Any]]) -> list[WalletActivityItem]:
    items: list[WalletActivityItem] = []
    for t in trades:
        side = str(t.get("side", "")).upper() or "—"
        ts = _parse_ts(t.get("timestamp") or t.get("createdAt") or t.get("matchTime"))
        trade_id = str(
            t.get("transactionHash") or t.get("id") or t.get("tradeId") or ""
        )
        items.append(
            WalletActivityItem(
                at=_fmt_ts(ts),
                source="polymarket",
                source_label="Polymarket",
                side=side,
                title=_trade_title(t),
                outcome=str(t.get("outcome", t.get("outcomeName", "")) or "—"),
                amount_usd=_trade_usd(t),
                price=float(t.get("price", 0) or 0),
                status="success",
                status_label="בוצע",
                detail="עסקה באתר / בארנק",
                trade_id=trade_id,
            )
        )
    return items


def _items_from_bot_orders(orders: list) -> list[WalletActivityItem]:
    items: list[WalletActivityItem] = []
    for o in orders:
        ok = o.status in ("filled", "submitted")
        items.append(
            WalletActivityItem(
                at=_fmt_ts(o.created_at.replace(tzinfo=timezone.utc) if o.created_at and o.created_at.tzinfo is None else o.created_at),
                source="bot",
                source_label="בוט",
                side=str(o.side).upper(),
                title=f"Token …{o.token_id[-8:]}" if len(o.token_id) > 8 else o.token_id,
                outcome="—",
                amount_usd=float(o.amount),
                price=0.0,
                status="success" if ok else "failed",
                status_label="בוצע" if ok else "נכשל",
                detail=(o.clob_response or "")[:120],
                trade_id=str(o.id),
            )
        )
    return items


def _items_from_audit(logs: list) -> list[WalletActivityItem]:
    items: list[WalletActivityItem] = []
    for row in logs:
        if row.event not in FAILED_EVENTS:
            continue
        if row.event == "manual_copy" and row.level != "error":
            continue
        items.append(
            WalletActivityItem(
                at=_fmt_ts(
                    row.created_at.replace(tzinfo=timezone.utc)
                    if row.created_at and row.created_at.tzinfo is None
                    else row.created_at
                ),
                source="bot",
                source_label="בוט",
                side="—",
                title=row.event,
                outcome="—",
                amount_usd=0.0,
                price=0.0,
                status="failed",
                status_label="נכשל",
                detail=row.message[:200],
                trade_id="",
            )
        )
    return items


def _sort_key(item: WalletActivityItem) -> str:
    return item.at or ""


def build_wallet_activity(config: AppConfig, repo: Repository | None = None) -> WalletActivitySummary:
    repo = repo or Repository(config)
    funder = config.funder_address
    if not funder:
        return WalletActivitySummary(
            configured=False,
            funder_address="",
            cash_usd=None,
            portfolio_usd=0.0,
            positions_count=0,
            open_orders_count=0,
            trades_count=0,
            failed_count=0,
            error="ארנק לא מוגדר — הגדר בדף ארנק",
        )

    cash: float | None = None
    open_orders = 0
    pm_trades: list[dict[str, Any]] = []
    positions: list[dict[str, Any]] = []
    err: str | None = None

    clob = ClobClientWrapper(config)
    if clob.is_configured:
        try:
            cash = clob.get_balance_details().get("balance")
        except Exception as exc:
            log.warning("wallet_activity_balance_failed", error=str(exc))
            err = f"יתרה: {exc}"
        open_orders = clob.count_open_orders()

    data = DataClient(config)
    try:
        pm_trades = data.get_all_trades(funder, max_pages=3, page_size=50)
        positions = data.get_positions(funder, limit=100)
    except Exception as exc:
        log.warning("wallet_activity_data_failed", error=str(exc))
        if err:
            err += f" · עסקאות: {exc}"
        else:
            err = str(exc)
    finally:
        data.close()

    portfolio = 0.0
    for p in positions:
        try:
            portfolio += float(p.get("currentValue", p.get("current_value", 0)) or 0)
        except (TypeError, ValueError):
            pass

    pm_items = _items_from_polymarket_trades(pm_trades)
    bot_orders = [o for o in repo.list_orders(limit=100) if o.status != "filled"]
    bot_items = _items_from_bot_orders(bot_orders)
    failed_items = _items_from_audit(repo.list_audit_logs(150))

    merged = pm_items + bot_items + [i for i in failed_items if i.status == "failed"]
    merged.sort(key=_sort_key, reverse=True)

    failed_count = sum(1 for i in merged if i.status == "failed")

    return WalletActivitySummary(
        configured=config.clob_configured,
        funder_address=funder,
        cash_usd=cash,
        portfolio_usd=round(portfolio, 2),
        positions_count=len(positions),
        open_orders_count=open_orders,
        trades_count=len(pm_items),
        failed_count=failed_count,
        error=err,
        items=merged[:100],
    )
