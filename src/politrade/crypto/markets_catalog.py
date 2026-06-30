"""Catalog of open crypto 5m markets with buy readiness and bot progress."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from politrade.api.clob_client import ClobClientWrapper
from politrade.config import AppConfig
from politrade.crypto.gamma_discovery import discover_5m_windows_from_gamma
from politrade.crypto.price_feed import (
    OracleSnapshot,
    TokenPrices,
    edge_pct_from_ask,
    fetch_token_prices,
    get_price_feed,
)
from politrade.crypto.strategy import DecisionAction, evaluate_window
from politrade.crypto.window import BetSide, WindowPhase, compute_window_ts
from politrade.storage.repository import Repository


@dataclass
class SideBuyStatus:
    side: str
    token_id: str
    ask: float | None
    edge_pct: float | None
    can_buy: bool
    block_reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "side": self.side,
            "token_id": self.token_id,
            "ask": self.ask,
            "edge_pct": round(self.edge_pct, 2) if self.edge_pct is not None else None,
            "can_buy": self.can_buy,
            "block_reason": self.block_reason,
        }


def _fmt_window_time(window_ts: int) -> str:
    start = datetime.fromtimestamp(window_ts, tz=timezone.utc)
    end = datetime.fromtimestamp(window_ts + 300, tz=timezone.utc)
    return f"{start.strftime('%H:%M')}–{end.strftime('%H:%M')} UTC"


def assess_side_buy(
    *,
    side: BetSide,
    window_closed: bool,
    phase: WindowPhase,
    token_id: str,
    ask: float | None,
    trading_ready: bool,
    already_bet: bool,
    min_bet_usd: float,
    cash_usd: float | None,
    has_liquidity: bool,
) -> SideBuyStatus:
    blocks: list[str] = []
    if not trading_ready:
        blocks.append("CLOB לא מחובר")
    if window_closed or phase == WindowPhase.CLOSED:
        blocks.append("שוק סגור")
    if already_bet:
        blocks.append("כבר הימרת בחלון")
    if not token_id:
        blocks.append("חסר token")
    if ask is None:
        blocks.append("אין מחיר")
    elif ask <= 0.01 or ask >= 0.99:
        blocks.append("מחיר לא סחיר")
    if not has_liquidity:
        blocks.append("אין נזילות")
    if cash_usd is not None and cash_usd < min_bet_usd:
        blocks.append(f"יתרה נמוכה (<${min_bet_usd:.0f})")

    return SideBuyStatus(
        side=side.value,
        token_id=token_id,
        ask=ask,
        edge_pct=edge_pct_from_ask(ask),
        can_buy=len(blocks) == 0,
        block_reason=" · ".join(blocks) if blocks else "",
    )


def _live_state_by_slug() -> dict[str, dict[str, Any]]:
    from politrade.crypto.runner import get_crypto_runner

    by_slug: dict[str, dict[str, Any]] = {}
    for item in get_crypto_runner().get_live_state().get("windows", []):
        slug = (item.get("window") or {}).get("slug")
        if slug:
            by_slug[slug] = item
    return by_slug


def _bet_for_window(repo: Repository, asset: str, window_ts: int):
    for b in repo.list_crypto_bets(100):
        if b.asset == asset and b.window_ts == window_ts and b.status not in ("failed", "skipped"):
            return b
    return None


def build_progress(
    *,
    phase: WindowPhase,
    already_bet: bool,
    bet_status: str | None,
    live: dict[str, Any] | None,
    auto_bet: bool,
) -> dict[str, Any]:
    if bet_status in ("won",):
        return {"stage": "won", "label": "זכייה ✓", "auto_active": False}
    if bet_status in ("lost",):
        return {"stage": "lost", "label": "הפסד", "auto_active": False}
    if bet_status == "open" or (already_bet and bet_status not in ("failed", "skipped")):
        return {"stage": "bet_open", "label": "הימור פתוח", "auto_active": False}

    decision = (live or {}).get("decision") or {}
    bet_placed = bool((live or {}).get("bet_placed"))
    action = decision.get("action", "wait")
    reason = decision.get("reason") or ""

    if bet_placed:
        return {"stage": "bet_placed", "label": "הימור בוצע ✓", "auto_active": auto_bet}

    if phase == WindowPhase.EARLY:
        return {
            "stage": "wait_early",
            "label": reason or "ממתין לחלון הימור",
            "auto_active": auto_bet,
        }
    if phase == WindowPhase.LATE:
        return {
            "stage": "wait_late",
            "label": reason or "חלון הימור נסגר",
            "auto_active": auto_bet,
        }
    if phase == WindowPhase.CLOSED:
        return {"stage": "closed", "label": "נסגר", "auto_active": False}

    if action == DecisionAction.BET.value:
        side = (decision.get("side") or "").upper()
        edge = decision.get("edge_pct")
        edge_s = f" · {edge:.1f}%" if edge is not None else ""
        return {
            "stage": "ready",
            "label": f"מוכן להמר {side}{edge_s}",
            "auto_active": auto_bet,
            "decision_side": decision.get("side"),
            "decision_edge_pct": decision.get("edge_pct"),
        }

    return {
        "stage": "monitoring",
        "label": reason or "מנטר…",
        "auto_active": auto_bet,
    }


def build_markets_catalog(
    config: AppConfig,
    *,
    repo: Repository | None = None,
    clob: ClobClientWrapper | None = None,
) -> dict[str, Any]:
    from politrade.crypto.strategy import crypto_cfg

    repo = repo or Repository(config)
    clob = clob or ClobClientWrapper(config)
    cfg = crypto_cfg(config)
    ahead = int(cfg.get("markets_ahead", 4))
    min_bet = float(cfg.get("bet_usd", 5))
    now_wts = compute_window_ts()

    cash: float | None = None
    trading_ready = clob.is_configured
    if clob.is_configured:
        details = clob.get_balance_details()
        cash = details.get("balance")
        if details.get("error") and cash is None:
            trading_ready = False

    feed = get_price_feed()
    live_by_slug = _live_state_by_slug()
    try:
        from politrade.crypto.runner import get_crypto_runner
        auto_bet = get_crypto_runner().get_live_state().get("auto_bet", True)
    except Exception:
        auto_bet = bool(cfg.get("auto_bet", True))

    windows = discover_5m_windows_from_gamma(config, markets_ahead=ahead)
    markets: list[dict[str, Any]] = []

    for window in windows:
        phase = window.phase()
        is_current = window.window_ts == now_wts
        tokens = fetch_token_prices(clob, window) if clob.is_configured else TokenPrices()
        oracle = feed.get_snapshot(window) if is_current else OracleSnapshot(
            asset=window.asset, window_ts=window.window_ts
        )
        already = repo.has_crypto_bet_for_window(window.asset.value, window.window_ts)
        bet = _bet_for_window(repo, window.asset.value, window.window_ts)
        live = live_by_slug.get(window.slug)

        decision_dict: dict[str, Any] = {}
        if is_current and live:
            decision_dict = live.get("decision") or {}
        elif is_current and clob.is_configured:
            decision = evaluate_window(
                window,
                oracle,
                tokens,
                config,
                already_bet=already,
                has_liquidity_fn=clob.has_buy_liquidity if clob.is_configured else None,
            )
            decision_dict = decision.to_dict()

        up_ask = tokens.up_ask or tokens.up_mid
        down_ask = tokens.down_ask or tokens.down_mid
        up_liq = up_ask is not None and 0.02 <= up_ask <= 0.98
        down_liq = down_ask is not None and 0.02 <= down_ask <= 0.98

        up_status = assess_side_buy(
            side=BetSide.UP,
            window_closed=window.closed,
            phase=phase,
            token_id=window.up_token_id,
            ask=up_ask,
            trading_ready=trading_ready,
            already_bet=already,
            min_bet_usd=min_bet,
            cash_usd=cash,
            has_liquidity=up_liq,
        )
        down_status = assess_side_buy(
            side=BetSide.DOWN,
            window_closed=window.closed,
            phase=phase,
            token_id=window.down_token_id,
            ask=down_ask,
            trading_ready=trading_ready,
            already_bet=already,
            min_bet_usd=min_bet,
            cash_usd=cash,
            has_liquidity=down_liq,
        )

        progress = build_progress(
            phase=phase,
            already_bet=already,
            bet_status=bet.status if bet else None,
            live=live,
            auto_bet=auto_bet,
        )

        markets.append({
            "asset": window.asset.value,
            "asset_label": window.asset.label,
            "window_ts": window.window_ts,
            "slug": window.slug,
            "title": window.title or window.slug,
            "phase": phase.value,
            "seconds_remaining": window.seconds_remaining(),
            "window_time": _fmt_window_time(window.window_ts),
            "is_current": is_current,
            "bot_enabled": True,
            "auto_eligible": is_current,
            "already_bet": already,
            "bet_status": bet.status if bet else None,
            "oracle_delta_pct": oracle.delta_pct,
            "decision": decision_dict,
            "progress": progress,
            "up": up_status.to_dict(),
            "down": down_status.to_dict(),
            "any_can_buy": up_status.can_buy or down_status.can_buy,
        })

    markets.sort(key=lambda m: (m["window_ts"], m["asset"]))
    open_count = len(markets)
    buyable_count = sum(1 for m in markets if m["any_can_buy"])
    current_count = sum(1 for m in markets if m["is_current"])

    return {
        "updated_at": time.time(),
        "source": "gamma:5M",
        "trading_ready": trading_ready,
        "cash_usd": cash,
        "min_bet_usd": min_bet,
        "markets_ahead": ahead,
        "open_count": open_count,
        "current_count": current_count,
        "buyable_count": buyable_count,
        "auto_bet": auto_bet,
        "markets": markets,
    }
