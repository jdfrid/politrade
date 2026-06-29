"""Resolve winning crypto bets and attempt redemption."""

from __future__ import annotations

import time

from politrade.api.clob_client import ClobClientWrapper
from politrade.config import AppConfig
from politrade.crypto.price_feed import get_price_feed
from politrade.crypto.window import BetSide, WINDOW_SECONDS
from politrade.logging_setup import get_logger
from politrade.storage.models import CryptoBet
from politrade.storage.repository import Repository

log = get_logger(__name__)


def resolve_open_bets(config: AppConfig | None = None, repo: Repository | None = None) -> int:
    """Mark bets won/lost after window closes."""
    from politrade.config import AppConfig

    cfg = config or AppConfig()
    r = repo or Repository(cfg)
    feed = get_price_feed()
    now = int(time.time())
    resolved = 0

    for bet in r.get_crypto_bets_needing_resolution():
        window_end = bet.window_ts + WINDOW_SECONDS
        if now < window_end + 5:
            continue

        open_px = bet.open_oracle_price
        close_px = feed.get_snapshot(
            _bet_window(bet)
        ).close_price or feed.get_snapshot(_bet_window(bet)).current_price

        if open_px is None or close_px is None:
            from politrade.crypto.window import CryptoAsset

            asset = CryptoAsset(bet.asset)
            close_px = feed.get_price(asset)
            if open_px is None and close_px:
                open_px = close_px

        if open_px is None or close_px is None:
            continue

        up_wins = close_px >= open_px
        bet_side_up = bet.side.lower() == BetSide.UP.value
        won = (bet_side_up and up_wins) or (not bet_side_up and not up_wins)

        if won:
            payout = bet.shares * 1.0
            pnl = payout - bet.bet_usd
        else:
            pnl = -bet.bet_usd

        r.resolve_crypto_bet(
            bet.id,
            won=won,
            oracle_close_price=close_px,
            realized_pnl=round(pnl, 4),
        )
        feed.set_close_price(
            _bet_window(bet).asset,
            bet.window_ts,
            close_px,
        )
        r.audit(
            "info",
            "crypto_bet_resolved",
            f"{bet.slug} {'won' if won else 'lost'} pnl={pnl:.2f}",
        )
        resolved += 1

    return resolved


def redeem_winning_bets(config: AppConfig | None = None, repo: Repository | None = None) -> int:
    """Attempt to sell winning tokens near $1 or mark redeemed."""
    from politrade.config import AppConfig

    cfg = config or AppConfig()
    r = repo or Repository(cfg)
    clob = ClobClientWrapper(cfg)
    if not clob.is_configured:
        return 0

    redeemed = 0
    for bet in r.get_crypto_bets_needing_redeem():
        try:
            mid = clob.get_mid_price(bet.token_id)
            if mid is not None and mid >= 0.95:
                resp = clob.market_sell(bet.token_id, bet.shares)
                log.info("crypto_redeem_sell", bet_id=bet.id, response=str(resp)[:200])
            r.mark_crypto_bet_redeemed(bet.id)
            r.audit("info", "crypto_bet_redeemed", f"bet_id={bet.id} slug={bet.slug}")
            redeemed += 1
        except Exception as exc:
            log.warning("crypto_redeem_failed", bet_id=bet.id, error=str(exc))

    return redeemed


def _bet_window(bet: CryptoBet):
    from politrade.crypto.window import CryptoAsset, CryptoWindow

    asset = CryptoAsset(bet.asset)
    return CryptoWindow(
        asset=asset,
        window_ts=bet.window_ts,
        slug=bet.slug,
        condition_id=bet.condition_id,
        up_token_id=bet.token_id if bet.side == "up" else "",
        down_token_id=bet.token_id if bet.side == "down" else "",
    )
