"""Monitor open positions and trigger exits."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from politrade.api.clob_client import ClobClientWrapper
from politrade.config import AppConfig
from politrade.execution.position_valuation import (
    ExitTargets,
    check_exit_reason,
    value_position,
)
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

    def targets(self) -> ExitTargets:
        return ExitTargets.from_config(self.config.exit)

    def check_all(self, *, dry_run: bool = False) -> list[str]:
        targets = self.targets()
        reasons: list[str] = []
        for pos in self.repo.get_open_positions():
            reason = self.check_position(pos, targets=targets, dry_run=dry_run)
            if reason:
                reasons.append(reason)
        return reasons

    def check_position(
        self,
        pos: Position,
        *,
        targets: ExitTargets | None = None,
        dry_run: bool = False,
        price: float | None = None,
    ) -> str | None:
        targets = targets or self.targets()
        if price is None:
            price = self._fetch_price(pos)
        valuation = value_position(pos, price, targets=targets)
        age_days = self._position_age_days(pos)
        exit_reason = check_exit_reason(pos, valuation, targets=targets, age_days=age_days)
        if exit_reason is None:
            return None

        log.info(
            "exit_triggered",
            position_id=pos.id,
            reason=exit_reason,
            current_value=valuation.current_value_usd,
            entry_cost=pos.entry_cost_usd,
        )

        if dry_run:
            self.notifier.send(
                f"[DRY RUN] Would SELL pos #{pos.id} ({exit_reason}) "
                f"value=${valuation.current_value_usd:.2f}"
            )
            return exit_reason

        if not self.clob.is_configured:
            return None

        try:
            self.clob.cancel_orders_for_token(pos.token_id)
            resp = self.clob.market_sell(pos.token_id, pos.shares)
            self.repo.close_position(
                pos.id,
                exit_price=price,
                realized_pnl=valuation.pnl_usd,
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
                f"SELL pos #{pos.id} ({exit_reason}) PnL=${valuation.pnl_usd:.2f}"
            )
            return exit_reason
        except Exception as exc:
            log.error("exit_failed", position_id=pos.id, error=str(exc))
            self.repo.audit("error", "exit_failed", str(exc))
            return None

    def _fetch_price(self, pos: Position) -> float:
        if self.clob.is_configured:
            mid = self.clob.get_mid_price(pos.token_id)
            if mid is not None:
                return mid
        return pos.entry_price

    @staticmethod
    def _position_age_days(pos: Position) -> int:
        if not pos.opened_at:
            return 0
        opened = pos.opened_at
        if opened.tzinfo is None:
            opened = opened.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - opened).days
