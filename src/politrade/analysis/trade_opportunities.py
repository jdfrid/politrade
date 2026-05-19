"""Recent leader trades ranked as copy opportunities."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

import httpx

from politrade.analysis.opportunity_cache import get_cached, set_cached
from politrade.api.data_client import DataClient
from politrade.api.rate_limit import configure_min_interval
from politrade.config import AppConfig
from politrade.logging_setup import get_logger
from politrade.signals.trade_selector import TradeSelector

log = get_logger(__name__)


@dataclass
class TradeOpportunity:
    trade_id: str
    leader_address: str
    market_id: str
    token_id: str
    title: str
    outcome: str
    side: str
    size_usd: float
    price: float
    leader_pnl_usd: float | None
    leader_pnl_pct: float | None
    traded_at: str
    copyable: bool
    block_reason: str = ""
    source: str = "trades"

    @property
    def pnl_label(self) -> str:
        if self.leader_pnl_usd is not None and self.leader_pnl_usd != 0:
            sign = "+" if self.leader_pnl_usd > 0 else ""
            return f"{sign}${self.leader_pnl_usd:.2f}"
        if self.leader_pnl_pct is not None:
            sign = "+" if self.leader_pnl_pct > 0 else ""
            return f"{sign}{self.leader_pnl_pct:.1f}%"
        return "—"


def _parse_ts(trade: dict[str, Any]) -> datetime | None:
    for key in ("timestamp", "createdAt", "created_at", "matchTime"):
        val = trade.get(key)
        if val is None:
            continue
        if isinstance(val, (int, float)):
            ts = float(val)
            if ts > 1e12:
                ts /= 1000
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        if isinstance(val, str):
            try:
                return datetime.fromisoformat(val.replace("Z", "+00:00"))
            except ValueError:
                continue
    return None


def _position_index(positions: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    idx: dict[str, dict[str, Any]] = {}
    for p in positions:
        for key in ("asset", "asset_id", "tokenId", "conditionId", "condition_id", "market"):
            val = p.get(key)
            if val:
                idx[str(val).lower()] = p
    return idx


def _pnl_from_position(pos: dict[str, Any]) -> tuple[float | None, float | None]:
    cash = pos.get("cashPnl", pos.get("cash_pnl"))
    pct = pos.get("percentPnl", pos.get("percent_pnl"))
    try:
        pnl_usd = float(cash) if cash is not None else None
    except (TypeError, ValueError):
        pnl_usd = None
    try:
        pnl_pct = float(pct) if pct is not None else None
    except (TypeError, ValueError):
        pnl_pct = None
    if pnl_usd is None and pnl_pct is not None:
        try:
            initial = float(pos.get("initialValue", pos.get("initial_value", 0)) or 0)
            if initial:
                pnl_usd = initial * (pnl_pct / 100)
        except (TypeError, ValueError):
            pass
    return pnl_usd, pnl_pct


def _trade_title(trade: dict[str, Any]) -> str:
    for key in ("title", "question", "marketTitle", "market_title", "name"):
        val = trade.get(key)
        if val:
            return str(val)[:120]
    mid = trade.get("conditionId") or trade.get("market") or "?"
    return f"Market {str(mid)[:16]}…"


def _position_title(pos: dict[str, Any]) -> str:
    for key in ("title", "question", "marketTitle", "name"):
        val = pos.get(key)
        if val:
            return str(val)[:120]
    return "פוזיציה פתוחה"


def _opportunities_from_positions(
    leader_address: str,
    leader_score: float,
    positions: list[dict[str, Any]],
    *,
    selector: TradeSelector,
    min_usd: float,
    limit: int,
) -> list[TradeOpportunity]:
    opportunities: list[TradeOpportunity] = []
    for pos in positions:
        try:
            size_usd = float(
                pos.get("initialValue", pos.get("initial_value", pos.get("currentValue", 0))) or 0
            )
        except (TypeError, ValueError):
            size_usd = 0
        if size_usd < min_usd:
            continue

        token_id = str(pos.get("asset", pos.get("asset_id", pos.get("tokenId", ""))) or "")
        market_id = str(pos.get("conditionId", pos.get("condition_id", pos.get("market", ""))) or "")
        if not token_id:
            continue

        pnl_usd, pnl_pct = _pnl_from_position(pos)
        price = float(pos.get("avgPrice", pos.get("curPrice", pos.get("price", 0))) or 0)

        pseudo_trade = {
            "asset": token_id,
            "conditionId": market_id,
            "side": "BUY",
            "price": price,
            "usdcSize": size_usd,
            "proxyWallet": leader_address,
            "id": f"pos_{token_id}",
        }
        signal = selector.evaluate(pseudo_trade, leader_score, manual=True)
        copyable = signal is not None
        block_reason = "" if copyable else _block_reason(selector, pseudo_trade, leader_score)

        opportunities.append(
            TradeOpportunity(
                trade_id=f"pos_{token_id}",
                leader_address=leader_address.lower(),
                market_id=market_id,
                token_id=token_id,
                title=_position_title(pos),
                outcome=str(pos.get("outcome", pos.get("outcomeName", "")) or "—"),
                side="BUY",
                size_usd=size_usd,
                price=price,
                leader_pnl_usd=pnl_usd,
                leader_pnl_pct=pnl_pct,
                traded_at="פוזיציה פתוחה",
                copyable=copyable,
                block_reason=block_reason,
                source="positions",
            )
        )

    def sort_key(o: TradeOpportunity) -> tuple:
        pnl = o.leader_pnl_usd if o.leader_pnl_usd is not None else -1e9
        pct = o.leader_pnl_pct if o.leader_pnl_pct is not None else -1e9
        return (-pnl, -pct, -o.size_usd)

    opportunities.sort(key=sort_key)
    good = [o for o in opportunities if (o.leader_pnl_usd or 0) > 0 or (o.leader_pnl_pct or 0) > 0]
    if good:
        return good[:limit]
    return opportunities[:limit]


def _opportunities_from_trades(
    leader_address: str,
    leader_score: float,
    trades: list[dict[str, Any]],
    positions: list[dict[str, Any]],
    *,
    selector: TradeSelector,
    min_usd: float,
    limit: int,
) -> list[TradeOpportunity]:
    pos_idx = _position_index(positions)
    opportunities: list[TradeOpportunity] = []

    for trade in trades:
        side = str(trade.get("side", "")).upper()
        if side != "BUY":
            continue

        size_usd = TradeSelector._trade_usd(trade)
        if size_usd < min_usd:
            continue

        token_id = TradeSelector._extract_token_id(trade) or ""
        market_id = TradeSelector._extract_market_id(trade) or ""
        trade_id = TradeSelector._trade_id(trade)
        price = float(trade.get("price", 0) or 0)

        pos = pos_idx.get(token_id.lower()) or pos_idx.get(market_id.lower())
        pnl_usd, pnl_pct = _pnl_from_position(pos) if pos else (None, None)

        if pnl_usd is None:
            for key in ("realizedPnl", "realized_pnl", "pnl"):
                val = trade.get(key)
                if val is not None:
                    try:
                        pnl_usd = float(val)
                        break
                    except (TypeError, ValueError):
                        pass

        ts = _parse_ts(trade)
        traded_at = ts.strftime("%Y-%m-%d %H:%M") if ts else "—"

        signal = selector.evaluate(trade, leader_score, manual=True)
        copyable = signal is not None
        block_reason = "" if copyable else _block_reason(selector, trade, leader_score)

        opportunities.append(
            TradeOpportunity(
                trade_id=trade_id,
                leader_address=leader_address.lower(),
                market_id=market_id,
                token_id=token_id,
                title=_trade_title(trade),
                outcome=str(trade.get("outcome", trade.get("outcomeName", "")) or "—"),
                side=side,
                size_usd=size_usd,
                price=price,
                leader_pnl_usd=pnl_usd,
                leader_pnl_pct=pnl_pct,
                traded_at=traded_at,
                copyable=copyable,
                block_reason=block_reason,
                source="trades",
            )
        )

    def sort_key(o: TradeOpportunity) -> tuple:
        pnl = o.leader_pnl_usd if o.leader_pnl_usd is not None else -1e9
        pct = o.leader_pnl_pct if o.leader_pnl_pct is not None else -1e9
        return (-pnl, -pct, -o.size_usd)

    opportunities.sort(key=sort_key)
    good = [o for o in opportunities if (o.leader_pnl_usd or 0) > 0 or (o.leader_pnl_pct or 0) > 0]
    if good:
        return good[:limit]
    return opportunities[:limit]


def fetch_leader_opportunities(
    leader_address: str,
    leader_score: float,
    *,
    config: AppConfig | None = None,
    limit: int = 5,
    trade_limit: int = 20,
    force_refresh: bool = False,
    use_cache: bool = True,
) -> list[TradeOpportunity]:
    """Return opportunities with cache + positions-first to reduce API calls."""
    cfg = config or AppConfig()
    ttl = int(cfg.leaders.get("opportunity_cache_ttl_minutes", 20))
    interval = float(cfg.api.get("min_request_interval_seconds", 1.25))
    configure_min_interval(interval)

    if use_cache and not force_refresh:
        cached = get_cached(leader_address, ttl_minutes=ttl)
        if cached is not None:
            return [TradeOpportunity(**d) for d in cached]

    selector = TradeSelector(cfg)
    min_usd = float(cfg.copy.get("min_leader_trade_usd", 10))
    positions_only = bool(cfg.leaders.get("opportunities_from_positions_only", True))
    data = DataClient(cfg)

    try:
        positions = data.get_positions(leader_address, limit=50)
        if positions_only:
            result = _opportunities_from_positions(
                leader_address, leader_score, positions,
                selector=selector, min_usd=min_usd, limit=limit,
            )
        else:
            trades = data.get_trades(leader_address, limit=trade_limit)
            result = _opportunities_from_trades(
                leader_address, leader_score, trades, positions,
                selector=selector, min_usd=min_usd, limit=limit,
            )
        set_cached(leader_address, [asdict(o) for o in result])
        return result
    finally:
        data.close()


def fetch_leader_opportunities_safe(
    leader_address: str,
    leader_score: float,
    **kwargs,
) -> tuple[list[TradeOpportunity], str | None, bool]:
    """
    Returns (opportunities, error_message, from_stale_cache).
    On 429, falls back to expired cache if available.
    """
    cfg = kwargs.get("config") or AppConfig()
    ttl = int(cfg.leaders.get("opportunity_cache_ttl_minutes", 20))

    try:
        return fetch_leader_opportunities(leader_address, leader_score, **kwargs), None, False
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code != 429:
            raise
        log.warning("rate_limited", leader=leader_address)
        stale_raw = get_cached(leader_address, ttl_minutes=ttl * 10)
        if stale_raw:
            stale = [TradeOpportunity(**d) for d in stale_raw]
            return stale, "מגבלת קצב API — מוצג מטמון ישן", True
        positions_only = bool(cfg.leaders.get("opportunities_from_positions_only", True))
        msg = "מגבלת קצב API — נסה שוב בעוד דקה"
        if positions_only:
            msg += " (לחץ רענן על מנהיג בודד)"
        return [], msg, False


def _block_reason(selector: TradeSelector, trade: dict, leader_score: float) -> str:
    cfg = selector.config
    if leader_score < float(cfg.copy.get("min_leader_score", 70)):
        return "ציון מנהיג נמוך"
    side = str(trade.get("side", "")).upper()
    if side != "BUY":
        return "לא קנייה"
    size = TradeSelector._trade_usd(trade)
    if size < float(cfg.copy.get("min_leader_trade_usd", 10)):
        return "עסקה קטנה מדי"
    if not TradeSelector._extract_token_id(trade):
        return "חסר token"
    market_id = TradeSelector._extract_market_id(trade)
    if market_id and selector.repo.has_open_position_for_market(market_id):
        return "כבר יש לנו פוזיציה בשוק"
    if selector.repo.count_open_positions() >= int(cfg.risk.get("max_open_positions", 5)):
        return "מקסימום פוזיציות פתוחות"
    return "לא עובר סינון"
