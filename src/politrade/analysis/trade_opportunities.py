"""Recent leader trades ranked as copy opportunities."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from politrade.api.data_client import DataClient
from politrade.config import AppConfig
from politrade.signals.trade_selector import TradeSelector


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


def fetch_leader_opportunities(
    leader_address: str,
    leader_score: float,
    *,
    config: AppConfig | None = None,
    limit: int = 5,
    trade_limit: int = 40,
) -> list[TradeOpportunity]:
    """Return recent BUY trades worth copying, sorted by leader profit."""
    cfg = config or AppConfig()
    data = DataClient(cfg)
    selector = TradeSelector(cfg)
    min_usd = float(cfg.copy.get("min_leader_trade_usd", 10))

    try:
        trades = data.get_trades(leader_address, limit=trade_limit)
        positions = data.get_positions(leader_address, limit=100)
    finally:
        data.close()

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

        signal = selector.evaluate(trade, leader_score)
        copyable = signal is not None
        block_reason = ""
        if not copyable:
            block_reason = _block_reason(selector, trade, leader_score)

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
