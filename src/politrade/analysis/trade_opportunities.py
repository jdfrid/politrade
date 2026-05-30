"""Recent leader trades ranked as copy opportunities."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
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


@dataclass
class OpportunityDiagnostics:
    """Counts explaining why opportunities were included or filtered out."""

    trades_seen: int = 0
    buy_trades: int = 0
    too_old: int = 0
    too_small: int = 0
    not_buy: int = 0
    negative_pnl: int = 0
    missing_token: int = 0
    missing_market: int = 0
    market_closed: int = 0
    blocked_other: int = 0
    copyable: int = 0
    positions_scanned: int = 0
    shown: int = 0

    def summary_he(self) -> str:
        parts = [f"נסרקו {self.trades_seen} עסקאות · {self.buy_trades} BUY"]
        if self.positions_scanned:
            parts.append(f"{self.positions_scanned} פוזיציות")
        parts.append(f"{self.copyable} ניתנות להעתקה · {self.shown} מוצגות")
        return " · ".join(parts)

    def rejections_he(self) -> str:
        items: list[str] = []
        if self.too_old:
            items.append(f"{self.too_old} ישנות מדי")
        if self.too_small:
            items.append(f"{self.too_small} קטנות מדי")
        if self.not_buy:
            items.append(f"{self.not_buy} לא קנייה")
        if self.negative_pnl:
            items.append(f"{self.negative_pnl} רווח שלילי")
        if self.missing_token:
            items.append(f"{self.missing_token} חסר token")
        if self.missing_market:
            items.append(f"{self.missing_market} חסר market")
        if self.market_closed:
            items.append(f"{self.market_closed} שוק סגור")
        if self.blocked_other:
            items.append(f"{self.blocked_other} סינון אחר")
        return " · ".join(items) if items else ""


@dataclass
class OpportunityResult:
    items: list[TradeOpportunity]
    scanned: int
    used_min_pct: float
    relaxed: bool = False
    diagnostics: OpportunityDiagnostics = field(default_factory=OpportunityDiagnostics)
    recent_items: list[TradeOpportunity] = field(default_factory=list)
    position_items: list[TradeOpportunity] = field(default_factory=list)


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


def _normalize_pct(pct: float | None) -> float | None:
    if pct is None:
        return None
    if abs(pct) <= 1.0:
        return pct * 100.0
    return pct


def _pnl_from_position(pos: dict[str, Any]) -> tuple[float | None, float | None]:
    cash = pos.get("cashPnl", pos.get("cash_pnl"))
    pct = pos.get("percentPnl", pos.get("percent_pnl"))
    try:
        pnl_usd = float(cash) if cash is not None else None
    except (TypeError, ValueError):
        pnl_usd = None
    try:
        pnl_pct = _normalize_pct(float(pct)) if pct is not None else None
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


def _opportunity_mode(cfg: AppConfig) -> str:
    mode = str(cfg.leaders.get("opportunity_mode", "recent_trades")).lower()
    if mode in ("recent_trades", "positions", "both"):
        return mode
    if bool(cfg.leaders.get("opportunities_from_positions_only", False)):
        return "positions"
    return "recent_trades"


def _max_trade_age_hours(cfg: AppConfig) -> int:
    return int(cfg.leaders.get("max_trade_age_hours", 48))


def _profit_thresholds(cfg: AppConfig) -> tuple[float, float, float]:
    min_pct = float(cfg.leaders.get("min_leader_profit_pct", 25))
    min_usd = float(cfg.leaders.get("min_leader_profit_usd", 0))
    fallback = float(cfg.leaders.get("min_leader_profit_pct_fallback", 10))
    return min_pct, min_usd, fallback


def _effective_pnl_pct(opp: TradeOpportunity) -> float | None:
    if opp.leader_pnl_pct is not None:
        return opp.leader_pnl_pct
    if opp.leader_pnl_usd is not None and opp.size_usd > 0:
        return 100.0 * opp.leader_pnl_usd / opp.size_usd
    return None


def _is_high_profit(opp: TradeOpportunity, min_pct: float, min_usd: float) -> bool:
    pct = _effective_pnl_pct(opp)
    if pct is None or pct < min_pct:
        return False
    if opp.leader_pnl_usd is not None and opp.leader_pnl_usd <= 0:
        return False
    if min_usd > 0 and opp.leader_pnl_usd is not None and opp.leader_pnl_usd < min_usd:
        return False
    return True


def _finalize_positions(
    opportunities: list[TradeOpportunity],
    *,
    limit: int,
    min_pct: float,
    min_usd: float,
    fallback_pct: float = 10.0,
    diagnostics: OpportunityDiagnostics | None = None,
) -> list[TradeOpportunity]:
    def sort_and_take(items: list[TradeOpportunity]) -> list[TradeOpportunity]:
        def sort_key(o: TradeOpportunity) -> tuple:
            pct = _effective_pnl_pct(o) or -1e9
            pnl = o.leader_pnl_usd if o.leader_pnl_usd is not None else -1e9
            return (-pct, -pnl, -o.size_usd)

        items.sort(key=sort_key)
        return items[:limit]

    primary = [o for o in opportunities if _is_high_profit(o, min_pct, min_usd)]
    if primary:
        result = sort_and_take(primary)
    elif fallback_pct < min_pct:
        fallback = [o for o in opportunities if _is_high_profit(o, fallback_pct, min_usd)]
        if fallback:
            result = sort_and_take(fallback)
        else:
            any_positive = [
                o for o in opportunities
                if (_effective_pnl_pct(o) or 0) > 0
                and (o.leader_pnl_usd is None or o.leader_pnl_usd > 0)
            ]
            result = sort_and_take(any_positive)
    else:
        any_positive = [
            o for o in opportunities
            if (_effective_pnl_pct(o) or 0) > 0
            and (o.leader_pnl_usd is None or o.leader_pnl_usd > 0)
        ]
        result = sort_and_take(any_positive)

    if diagnostics:
        diagnostics.shown = len(result)
    return result


def _finalize_recent_trades(
    opportunities: list[TradeOpportunity],
    *,
    limit: int,
    diagnostics: OpportunityDiagnostics | None = None,
) -> list[TradeOpportunity]:
    def sort_key(o: TradeOpportunity) -> tuple:
        return (-o.size_usd, o.traded_at)

    sorted_opps = sorted(opportunities, key=sort_key)
    result = sorted_opps[:limit]
    if diagnostics:
        diagnostics.shown = len(result)
    return result


def _merge_opportunities(
    recent: list[TradeOpportunity],
    positions: list[TradeOpportunity],
    *,
    limit: int,
) -> list[TradeOpportunity]:
    seen: set[str] = set()
    merged: list[TradeOpportunity] = []
    for opp in recent + positions:
        key = opp.token_id or opp.trade_id
        if key in seen:
            continue
        seen.add(key)
        merged.append(opp)
    recent_sorted = sorted(
        [o for o in merged if o.source == "trades"],
        key=lambda o: (-o.size_usd, o.traded_at),
    )
    pos_sorted = sorted(
        [o for o in merged if o.source == "positions"],
        key=lambda o: (-(_effective_pnl_pct(o) or 0), -o.size_usd),
    )
    half = max(1, limit // 2)
    combined = recent_sorted[:half] + pos_sorted[: limit - half]
    return combined[:limit]


def _position_title(pos: dict[str, Any]) -> str:
    for key in ("title", "question", "marketTitle", "name"):
        val = pos.get(key)
        if val:
            return str(val)[:120]
    return "פוזיציה פתוחה"


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
    if not market_id:
        return "חסר market_id"
    if selector.repo.has_open_position_for_market(market_id):
        return "כבר יש לנו פוזיציה בשוק"
    if selector.repo.count_open_positions() >= int(cfg.risk.get("max_open_positions", 5)):
        return "מקסימום פוזיציות פתוחות"
    if not selector._market_active(market_id):
        return "שוק סגור"
    return "לא עובר סינון"


def _record_block(diag: OpportunityDiagnostics, reason: str) -> None:
    if reason == "עסקה ישנה מדי":
        diag.too_old += 1
    elif reason == "עסקה קטנה מדי":
        diag.too_small += 1
    elif reason == "לא קנייה":
        diag.not_buy += 1
    elif reason == "חסר token":
        diag.missing_token += 1
    elif reason == "חסר market_id":
        diag.missing_market += 1
    elif reason == "שוק סגור":
        diag.market_closed += 1
    else:
        diag.blocked_other += 1


def _build_opportunities_from_positions(
    leader_address: str,
    leader_score: float,
    positions: list[dict[str, Any]],
    *,
    selector: TradeSelector,
    min_usd: float,
    diagnostics: OpportunityDiagnostics,
) -> list[TradeOpportunity]:
    opportunities: list[TradeOpportunity] = []
    diagnostics.positions_scanned = len(positions)
    for pos in positions:
        try:
            size_usd = float(
                pos.get("initialValue", pos.get("initial_value", pos.get("currentValue", 0))) or 0
            )
        except (TypeError, ValueError):
            size_usd = 0
        if size_usd < min_usd:
            diagnostics.too_small += 1
            continue

        token_id = str(pos.get("asset", pos.get("asset_id", pos.get("tokenId", ""))) or "")
        market_id = str(pos.get("conditionId", pos.get("condition_id", pos.get("market", ""))) or "")
        if not token_id:
            diagnostics.missing_token += 1
            continue

        pnl_usd, pnl_pct = _pnl_from_position(pos)
        if pnl_usd is not None and pnl_usd <= 0 and (pnl_pct is None or pnl_pct <= 0):
            diagnostics.negative_pnl += 1
            continue
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
        if copyable:
            diagnostics.copyable += 1
        elif block_reason:
            _record_block(diagnostics, block_reason)

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
    return opportunities


def _build_opportunities_from_trades(
    leader_address: str,
    leader_score: float,
    trades: list[dict[str, Any]],
    positions: list[dict[str, Any]],
    *,
    selector: TradeSelector,
    min_usd: float,
    max_age_hours: int,
    require_positive_pnl: bool,
    diagnostics: OpportunityDiagnostics,
) -> list[TradeOpportunity]:
    pos_idx = _position_index(positions)
    opportunities: list[TradeOpportunity] = []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
    diagnostics.trades_seen = len(trades)

    for trade in trades:
        side = str(trade.get("side", "")).upper()
        if side != "BUY":
            diagnostics.not_buy += 1
            continue
        diagnostics.buy_trades += 1

        ts = _parse_ts(trade)
        if ts and ts < cutoff:
            diagnostics.too_old += 1
            continue

        size_usd = TradeSelector._trade_usd(trade)
        if size_usd < min_usd:
            diagnostics.too_small += 1
            continue

        token_id = TradeSelector._extract_token_id(trade) or ""
        market_id = TradeSelector._extract_market_id(trade) or ""
        trade_id = TradeSelector._trade_id(trade)
        price = float(trade.get("price", 0) or 0)

        pos = pos_idx.get(token_id.lower()) or pos_idx.get(market_id.lower())
        pnl_usd, pnl_pct = _pnl_from_position(pos) if pos else (None, None)

        if require_positive_pnl and pnl_usd is not None and pnl_usd <= 0 and (pnl_pct is None or pnl_pct <= 0):
            diagnostics.negative_pnl += 1
            continue

        traded_at = ts.strftime("%Y-%m-%d %H:%M") if ts else "—"

        signal = selector.evaluate(trade, leader_score, manual=True)
        copyable = signal is not None
        block_reason = "" if copyable else _block_reason(selector, trade, leader_score)
        if copyable:
            diagnostics.copyable += 1
        elif block_reason:
            _record_block(diagnostics, block_reason)

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
    return opportunities


def _apply_finalize(
    raw_recent: list[TradeOpportunity],
    raw_positions: list[TradeOpportunity],
    *,
    mode: str,
    limit: int,
    min_pct: float,
    min_usd: float,
    fallback_pct: float,
    diagnostics: OpportunityDiagnostics,
) -> OpportunityResult:
    recent_final: list[TradeOpportunity] = []
    pos_final: list[TradeOpportunity] = []

    if mode in ("recent_trades", "both"):
        recent_final = _finalize_recent_trades(raw_recent, limit=limit, diagnostics=diagnostics)
    if mode in ("positions", "both"):
        pos_diag = OpportunityDiagnostics()
        pos_final = _finalize_positions(
            raw_positions,
            limit=limit,
            min_pct=min_pct,
            min_usd=min_usd,
            fallback_pct=fallback_pct,
            diagnostics=pos_diag,
        )

    if mode == "both":
        items = _merge_opportunities(recent_final, pos_final, limit=limit)
    elif mode == "recent_trades":
        items = recent_final
    else:
        items = pos_final

    diagnostics.shown = len(items)
    scanned = len(raw_recent) + len(raw_positions)
    used_min = 0.0 if mode == "recent_trades" else min_pct
    relaxed = mode == "recent_trades"

    return OpportunityResult(
        items=items,
        scanned=scanned,
        used_min_pct=used_min,
        relaxed=relaxed,
        diagnostics=diagnostics,
        recent_items=recent_final,
        position_items=pos_final,
    )


def fetch_leader_opportunities(
    leader_address: str,
    leader_score: float,
    *,
    config: AppConfig | None = None,
    limit: int = 5,
    trade_limit: int = 50,
    force_refresh: bool = False,
    use_cache: bool = True,
) -> OpportunityResult:
    """Return opportunities with cache; mode from config (recent_trades / positions / both)."""
    cfg = config or AppConfig()
    ttl = int(cfg.leaders.get("opportunity_cache_ttl_minutes", 20))
    interval = float(cfg.api.get("min_request_interval_seconds", 1.25))
    configure_min_interval(interval)

    mode = _opportunity_mode(cfg)
    max_age = _max_trade_age_hours(cfg)
    min_profit_pct, min_profit_usd, fallback_pct = _profit_thresholds(cfg)

    if use_cache and not force_refresh:
        cached = get_cached(leader_address, ttl_minutes=ttl)
        if cached is not None:
            payload = cached if isinstance(cached, dict) else {"recent": cached, "positions": []}
            if isinstance(cached, list):
                payload = {"recent": cached, "positions": []}
            raw_recent = [TradeOpportunity(**d) for d in payload.get("recent", [])]
            raw_positions = [TradeOpportunity(**d) for d in payload.get("positions", [])]
            diag = OpportunityDiagnostics()
            return _apply_finalize(
                raw_recent, raw_positions,
                mode=mode, limit=limit,
                min_pct=min_profit_pct, min_usd=min_profit_usd, fallback_pct=fallback_pct,
                diagnostics=diag,
            )

    selector = TradeSelector(cfg)
    min_usd = float(cfg.copy.get("min_leader_trade_usd", 10))
    data = DataClient(cfg)
    diagnostics = OpportunityDiagnostics()

    try:
        positions = data.get_positions(leader_address, limit=50)
        raw_recent: list[TradeOpportunity] = []
        raw_positions: list[TradeOpportunity] = []

        if mode in ("recent_trades", "both"):
            trades = data.get_trades(leader_address, limit=trade_limit)
            raw_recent = _build_opportunities_from_trades(
                leader_address, leader_score, trades, positions,
                selector=selector, min_usd=min_usd, max_age_hours=max_age,
                require_positive_pnl=False, diagnostics=diagnostics,
            )
        if mode in ("positions", "both"):
            pos_diag = OpportunityDiagnostics()
            raw_positions = _build_opportunities_from_positions(
                leader_address, leader_score, positions,
                selector=selector, min_usd=min_usd, diagnostics=pos_diag,
            )
            diagnostics.positions_scanned = pos_diag.positions_scanned
            diagnostics.copyable += pos_diag.copyable

        cache_payload = {
            "recent": [asdict(o) for o in raw_recent],
            "positions": [asdict(o) for o in raw_positions],
        }
        set_cached(leader_address, cache_payload)
        return _apply_finalize(
            raw_recent, raw_positions,
            mode=mode, limit=limit,
            min_pct=min_profit_pct, min_usd=min_profit_usd, fallback_pct=fallback_pct,
            diagnostics=diagnostics,
        )
    finally:
        data.close()


def fetch_leader_opportunities_safe(
    leader_address: str,
    leader_score: float,
    **kwargs,
) -> tuple[OpportunityResult, str | None, bool]:
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
            mode = _opportunity_mode(cfg)
            min_pct, min_usd_p, fallback_pct = _profit_thresholds(cfg)
            limit = int(kwargs.get("limit", 5))
            if isinstance(stale_raw, list):
                payload = {"recent": stale_raw, "positions": []}
            else:
                payload = stale_raw
            raw_recent = [TradeOpportunity(**d) for d in payload.get("recent", [])]
            raw_positions = [TradeOpportunity(**d) for d in payload.get("positions", [])]
            stale = _apply_finalize(
                raw_recent, raw_positions,
                mode=mode, limit=limit,
                min_pct=min_pct, min_usd=min_usd_p, fallback_pct=fallback_pct,
                diagnostics=OpportunityDiagnostics(),
            )
            return stale, "מגבלת קצב API — מוצג מטמון ישן", True
        return OpportunityResult(items=[], scanned=0, used_min_pct=0), "מגבלת קצב API — נסה שוב בעוד דקה", False
