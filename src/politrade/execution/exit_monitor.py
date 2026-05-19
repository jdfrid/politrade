"""Monitor open positions and trigger exits."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from politrade.api.clob_client import ClobClientWrapper
from politrade.config import AppConfig
from politrade.logging_setup import get_logger
from politrade.notifications import Notifier
from politrade.storage.models import Position
from politrade.storage.repository import Repository

log = get_logger(__name__)


class ExitMonitor:
    def __init__(
        self,
        config: AppConfig | None = None,
        repo: Repository | None = None,
        clob: ClobClientWrapper | None = None,
        notifier: Notifier | None = None,
    ) -> None:
        self.config = config or AppConfig()
        self.repo = repo or Repository(self.config)
        self.clob = clob or ClobClientWrapper(self.config)
        self.notifier = notifier or Notifier(self.config)

    def check_all(self, *, dry_run: bool = False) -> list[str]:
        exit_cfg = self.config.exit
        tp_mult = float(exit_cfg.get("take_profit_multiplier", 2.0))
        sl_mult = float(exit_cfg.get("stop_loss_multiplier", 0.5))
        max_hold_days = int(exit_cfg.get("max_hold_days", 30))

        reasons: list[str] = []
        for pos in self.repo.get_open_positions():
            reason = self._check_position(pos, tp_mult, sl_mult, max_hold_days, dry_run=dry_run)
            if reason:
                reasons.append(reason)
        return reasons

    def _check_position(
        self,
        pos: Position,
        tp_mult: float,
        sl_mult: float,
        max_hold_days: int,
        *,
        dry_run: bool,
    ) -> str | None:
        price = None
        if self.clob.is_configured:
            price = self.clob.get_mid_price(pos.token_id)
        if price is None:
            price = pos.entry_price

        current_value = pos.shares * price
        entry_cost = pos.entry_cost_usd

        exit_reason: str | None = None
        if current_value >= entry_cost * tp_mult:
            exit_reason = "take_profit_2x"
        elif current_value <= entry_cost * sl_mult:
            exit_reason = "stop_loss"
        elif pos.opened_at:
            opened = pos.opened_at
            if opened.tzinfo is None:
                opened = opened.replace(tzinfo=timezone.utc)
            age_days = (datetime.now(timezone.utc) - opened).days
            if age_days > max_hold_days:
                exit_reason = "max_hold_time"

        if exit_reason is None:
            return None

        log.info(
            "exit_triggered",
            position_id=pos.id,
            reason=exit_reason,
            current_value=current_value,
            entry_cost=entry_cost,
        )

        if dry_run:
            self.notifier.send(
                f"[DRY RUN] Would SELL pos #{pos.id} ({exit_reason}) value=${current_value:.2f}"
            )
            return exit_reason

        if not self.clob.is_configured:
            return None

        try:
            self.clob.cancel_orders_for_token(pos.token_id)
            resp = self.clob.market_sell(pos.token_id, pos.shares)
            realized_pnl = current_value - entry_cost
            self.repo.close_position(
                pos.id,
                exit_price=price,
                realized_pnl=realized_pnl,
                exit_reason=exit_reason,
            )
            self.repo.record_order(
                position_id=pos.id,
                token_id=pos.token_id,
                side="SELL",
                amount=pos.shares,
                clob_response=json.dumps(resp)[:4000] if isinstance(resp, dict) else str(resp)[:4000],
                status="filled",
            )
            self.notifier.send(
                f"SELL pos #{pos.id} ({exit_reason}) PnL=${realized_pnl:.2f}"
            )
            return exit_reason
        except Exception as exc:
            log.error("exit_failed", position_id=pos.id, error=str(exc))
            self.repo.audit("error", "exit_failed", str(exc))
            return None
