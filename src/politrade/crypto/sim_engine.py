"""Virtual bet execution and resolution for simulation."""

from __future__ import annotations

import time
from typing import Any

from politrade.config import AppConfig
from politrade.crypto.price_feed import get_price_feed
from politrade.crypto.strategy import StrategyDecision
from politrade.crypto.window import BetSide, CryptoWindow, WINDOW_SECONDS
from politrade.logging_setup import get_logger
from politrade.storage.models import SimBet
from politrade.storage.repository import Repository

log = get_logger(__name__)


def execute_sim_bet(
    repo: Repository,
    window: CryptoWindow,
    decision: StrategyDecision,
    *,
    bet_usd: float,
    open_oracle_price: float | None,
) -> SimBet | None:
    if decision.action.value != "bet" or not decision.side or bet_usd <= 0:
        return None
    if repo.has_sim_bet_for_window(window.asset.value, window.window_ts):
        return None

    balance = repo.get_sim_balance()
    if balance < bet_usd:
        log.info("sim_bet_insufficient_balance", slug=window.slug, need=bet_usd, have=balance)
        return None

    entry_price = decision.entry_ask or 0.5
    if entry_price <= 0:
        entry_price = 0.5
    shares = bet_usd / entry_price

    token_id = decision.token_id or (
        window.up_token_id if decision.side == BetSide.UP else window.down_token_id
    )

    repo.adjust_sim_balance(-bet_usd)
    from politrade.crypto.decision_rationale import factors_to_json

    bet = repo.create_sim_bet(
        asset=window.asset.value,
        window_ts=window.window_ts,
        slug=window.slug,
        side=decision.side.value,
        token_id=token_id,
        open_oracle_price=open_oracle_price,
        entry_price=entry_price,
        bet_usd=bet_usd,
        shares=shares,
        edge_pct=decision.edge_pct,
        decision_reason=decision.reason,
        rationale_he=decision.rationale_he,
        factors_json=factors_to_json(decision.factors),
        blocker_category=decision.blocker_category,
        seconds_at_entry=decision.seconds_elapsed,
    )
    repo.audit("info", "sim_bet_placed", f"{window.slug} {decision.side.value} ${bet_usd:.2f}")
    return bet


def resolve_sim_bets_for_window(
    window_ts: int,
    config: AppConfig | None = None,
    repo: Repository | None = None,
) -> int:
    from politrade.config import AppConfig

    cfg = config or AppConfig()
    r = repo or Repository(cfg)
    feed = get_price_feed()
    now = int(time.time())
    if now < window_ts + WINDOW_SECONDS + 3:
        return 0

    resolved = 0
    for bet in r.get_sim_bets_for_window(window_ts):
        if bet.status != "open":
            continue
        result = _resolve_one_bet(bet, feed, r)
        if result is None:
            continue
        won, pnl = result
        if won:
            r.adjust_sim_balance(bet.shares * 1.0)
        r.add_sim_cumulative_pnl(pnl)
        resolved += 1
    return resolved


def _resolve_one_bet(bet: SimBet, feed, repo: Repository) -> tuple[bool, float] | None:
    from politrade.crypto.window import CryptoAsset, CryptoWindow

    try:
        asset = CryptoAsset(bet.asset)
    except ValueError:
        return None

    window = CryptoWindow(
        asset=asset,
        window_ts=bet.window_ts,
        slug=bet.slug,
        up_token_id=bet.token_id if bet.side == "up" else "",
        down_token_id=bet.token_id if bet.side == "down" else "",
    )
    snap = feed.get_snapshot(window)
    open_px = bet.open_oracle_price
    close_px = snap.close_price or snap.current_price or feed.get_price(asset)

    if open_px is None or close_px is None:
        return None

    up_wins = close_px >= open_px
    bet_side_up = bet.side.lower() == BetSide.UP.value
    won = (bet_side_up and up_wins) or (not bet_side_up and not up_wins)

    if won:
        pnl = bet.shares * 1.0 - bet.bet_usd
    else:
        pnl = -bet.bet_usd

    repo.resolve_sim_bet(
        bet.id,
        won=won,
        oracle_close_price=close_px,
        realized_pnl=round(pnl, 4),
    )
    feed.set_close_price(asset, bet.window_ts, close_px)
    repo.audit(
        "info",
        "sim_bet_resolved",
        f"{bet.slug} {'won' if won else 'lost'} pnl={pnl:.2f}",
    )
    return won, pnl


def sim_bet_to_dict(bet: SimBet) -> dict[str, Any]:
    import json as _json

    factors = []
    if bet.factors_json:
        try:
            factors = _json.loads(bet.factors_json)
        except _json.JSONDecodeError:
            pass
    return {
        "id": bet.id,
        "asset": bet.asset.upper(),
        "window_ts": bet.window_ts,
        "slug": bet.slug,
        "side": bet.side,
        "bet_usd": bet.bet_usd,
        "entry_price": bet.entry_price,
        "edge_pct": bet.edge_pct,
        "status": bet.status,
        "realized_pnl": bet.realized_pnl,
        "decision_reason": bet.decision_reason,
        "rationale_he": bet.rationale_he,
        "factors": factors,
        "blocker_category": bet.blocker_category,
        "seconds_at_entry": bet.seconds_at_entry,
        "created_at": bet.created_at.isoformat() if bet.created_at else "",
    }
