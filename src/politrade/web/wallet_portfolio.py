"""Parse Polymarket portfolio data to match the official UI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class PortfolioPosition:
    title: str
    outcome: str
    slug: str
    icon: str
    size: float
    avg_price: float
    cur_price: float
    traded_usd: float
    to_win_usd: float
    current_value: float
    cash_pnl: float
    percent_pnl: float
    realized_pnl: float
    redeemable: bool
    token_id: str = ""
    condition_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "outcome": self.outcome,
            "slug": self.slug,
            "icon": self.icon,
            "size": round(self.size, 2),
            "avg_price": self.avg_price,
            "cur_price": self.cur_price,
            "avg_cents": round(self.avg_price * 100, 1),
            "cur_cents": round(self.cur_price * 100, 1),
            "traded_usd": round(self.traded_usd, 2),
            "to_win_usd": round(self.to_win_usd, 2),
            "current_value": round(self.current_value, 2),
            "cash_pnl": round(self.cash_pnl, 2),
            "percent_pnl": round(self.percent_pnl, 2),
            "realized_pnl": round(self.realized_pnl, 2),
            "redeemable": self.redeemable,
            "token_id": self.token_id,
            "condition_id": self.condition_id,
        }


def parse_portfolio_position(raw: dict[str, Any]) -> PortfolioPosition | None:
    size = float(raw.get("size") or 0)
    if size < 0.01:
        return None
    avg = float(raw.get("avgPrice") or raw.get("avg_price") or 0)
    cur = float(raw.get("curPrice") or raw.get("cur_price") or avg)
    traded = float(
        raw.get("initialValue")
        or raw.get("initial_value")
        or raw.get("totalBought")
        or raw.get("total_bought")
        or (size * avg if avg else 0)
    )
    current = float(raw.get("currentValue") or raw.get("current_value") or (size * cur))
    cash_pnl = float(raw.get("cashPnl") or raw.get("cash_pnl") or (current - traded))
    pct = float(raw.get("percentPnl") or raw.get("percent_pnl") or 0)
    if pct == 0 and traded > 0:
        pct = (cash_pnl / traded) * 100
    realized = float(raw.get("realizedPnl") or raw.get("realized_pnl") or 0)
    return PortfolioPosition(
        title=str(raw.get("title") or raw.get("question") or "—")[:120],
        outcome=str(raw.get("outcome") or raw.get("outcomeName") or "—"),
        slug=str(raw.get("slug") or raw.get("eventSlug") or ""),
        icon=str(raw.get("icon") or ""),
        size=size,
        avg_price=avg,
        cur_price=cur,
        traded_usd=traded,
        to_win_usd=size,
        current_value=current,
        cash_pnl=cash_pnl,
        percent_pnl=pct,
        realized_pnl=realized,
        redeemable=bool(raw.get("redeemable")),
        token_id=str(raw.get("asset") or raw.get("asset_id") or raw.get("tokenId") or ""),
        condition_id=str(raw.get("conditionId") or raw.get("condition_id") or ""),
    )


def build_portfolio_summary(
    positions_raw: list[dict[str, Any]],
    *,
    cash_usd: float | None,
    value_api: float | None = None,
) -> dict[str, Any]:
    positions: list[PortfolioPosition] = []
    for raw in positions_raw:
        pos = parse_portfolio_position(raw)
        if pos:
            positions.append(pos)

    positions_value = sum(p.current_value for p in positions)
    if value_api is not None and value_api > positions_value:
        positions_value = value_api

    traded_total = sum(p.traded_usd for p in positions)
    unrealized = sum(p.cash_pnl for p in positions)
    realized = sum(p.realized_pnl for p in positions)
    cash = float(cash_usd) if cash_usd is not None else None
    total_value = (cash or 0.0) + positions_value

    return {
        "total_value_usd": round(total_value, 2),
        "cash_usd": round(cash, 2) if cash is not None else None,
        "positions_value_usd": round(positions_value, 2),
        "traded_total_usd": round(traded_total, 2),
        "unrealized_pnl_usd": round(unrealized, 2),
        "realized_pnl_usd": round(realized, 2),
        "total_pnl_usd": round(unrealized + realized, 2),
        "positions": [p.to_dict() for p in positions],
        "positions_count": len(positions),
    }
