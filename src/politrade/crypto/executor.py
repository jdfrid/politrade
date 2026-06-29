"""Execute crypto Up/Down bets on CLOB."""

from __future__ import annotations

import json
from typing import Any

from politrade.api.clob_client import ClobClientWrapper
from politrade.config import AppConfig
from politrade.crypto.strategy import StrategyDecision, crypto_cfg
from politrade.crypto.window import CryptoWindow
from politrade.execution.clob_errors import format_clob_error
from politrade.execution.risk import RiskManager
from politrade.logging_setup import get_logger
from politrade.storage.models import CryptoBet
from politrade.storage.repository import Repository

log = get_logger(__name__)


class CryptoBetExecutor:
    def __init__(
        self,
        config: AppConfig | None = None,
        repo: Repository | None = None,
        clob: ClobClientWrapper | None = None,
    ) -> None:
        self.config = config or AppConfig()
        self.repo = repo or Repository(self.config)
        self.clob = clob or ClobClientWrapper(self.config)
        self.risk = RiskManager(self.config, self.repo, self.clob)

    def execute_bet(
        self,
        window: CryptoWindow,
        decision: StrategyDecision,
        *,
        bet_usd: float | None = None,
        open_oracle_price: float | None = None,
        dry_run: bool = False,
    ) -> CryptoBet | None:
        if decision.action.value != "bet" or not decision.token_id:
            return None

        cfg = crypto_cfg(self.config)
        amount = bet_usd if bet_usd is not None else float(cfg.get("bet_usd", 5))

        if self.risk.is_kill_switch_active():
            self.repo.audit("info", "crypto_bet_blocked", "kill switch active")
            return None

        if self.repo.has_crypto_bet_for_window(window.asset.value, window.window_ts):
            return None

        open_bets = self.repo.get_open_crypto_bets()
        max_open = int(self.config.risk.get("max_open_positions", 5))
        if len(open_bets) >= max_open:
            self.repo.audit("info", "crypto_bet_blocked", f"max open bets {max_open}")
            return None

        max_bet = float(self.config.risk.get("max_position_usd", 50))
        amount = min(amount, max_bet)

        entry_price = decision.entry_ask or 0.5

        if dry_run:
            log.info("crypto_dry_run", slug=window.slug, side=decision.side, amount=amount)
            return None

        if not self.clob.is_configured:
            self.repo.audit("error", "crypto_bet_failed", "CLOB not configured")
            return None

        try:
            resp = self.clob.market_buy(decision.token_id, amount)
            if entry_price <= 0:
                entry_price = self.clob.get_mid_price(decision.token_id) or 0.5
            shares = amount / entry_price if entry_price > 0 else amount

            bet = self.repo.create_crypto_bet(
                asset=window.asset.value,
                window_ts=window.window_ts,
                slug=window.slug,
                side=decision.side.value if decision.side else "",
                token_id=decision.token_id,
                condition_id=window.condition_id,
                open_oracle_price=open_oracle_price,
                entry_price=entry_price,
                bet_usd=amount,
                shares=shares,
                edge_pct=decision.edge_pct,
                status="open",
            )
            self.repo.record_order(
                position_id=None,
                token_id=decision.token_id,
                side="BUY",
                amount=amount,
                clob_response=json.dumps(resp)[:2000] if isinstance(resp, dict) else str(resp)[:2000],
                status="submitted",
            )
            self.repo.audit(
                "info",
                "crypto_bet_placed",
                f"{window.slug} {decision.side} ${amount:.2f} edge={decision.edge_pct:.1f}%",
            )
            log.info("crypto_bet_placed", bet_id=bet.id, slug=window.slug)
            return bet
        except Exception as exc:
            msg = format_clob_error(exc)
            self.repo.audit("error", "crypto_bet_failed", msg)
            log.error("crypto_bet_failed", slug=window.slug, error=msg)
            return None
