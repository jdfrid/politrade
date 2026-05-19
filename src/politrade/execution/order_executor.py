"""Execute copy trades on CLOB."""

from __future__ import annotations

import json

from politrade.api.clob_client import ClobClientWrapper
from politrade.config import AppConfig
from politrade.execution.risk import RiskManager
from politrade.logging_setup import get_logger
from politrade.notifications import Notifier
from politrade.signals.trade_selector import CopySignal
from politrade.storage.repository import Repository

log = get_logger(__name__)

FAILED_TRADES: set[str] = set()


class OrderExecutor:
    def __init__(
        self,
        config: AppConfig | None = None,
        repo: Repository | None = None,
        clob: ClobClientWrapper | None = None,
        risk: RiskManager | None = None,
        notifier: Notifier | None = None,
    ) -> None:
        self.config = config or AppConfig()
        self.repo = repo or Repository(self.config)
        self.clob = clob or ClobClientWrapper(self.config)
        self.risk = risk or RiskManager(self.config, self.repo, self.clob)
        self.notifier = notifier or Notifier(self.config)

    def execute(self, signal: CopySignal, *, dry_run: bool = False) -> bool:
        if signal.leader_trade_id in FAILED_TRADES:
            log.info("skip_failed_trade", trade_id=signal.leader_trade_id)
            return False

        decision = self.risk.evaluate(signal)
        if not decision.approved:
            log.info("risk_rejected", reason=decision.reason, leader=signal.leader_address)
            self.repo.audit("info", "risk_rejected", decision.reason)
            return False

        size = decision.position_size_usd
        if dry_run:
            log.info(
                "dry_run_buy",
                token=signal.token_id,
                size=size,
                leader=signal.leader_address,
            )
            self.notifier.send(f"[DRY RUN] Would BUY ${size:.2f} on {signal.market_id}")
            return True

        if not self.clob.is_configured:
            log.error("clob_not_configured")
            return False

        try:
            resp = self.clob.market_buy(signal.token_id, size)
            entry_price = signal.leader_price or 0.01
            if entry_price <= 0:
                entry_price = self.clob.get_mid_price(signal.token_id) or 0.5
            shares = size / entry_price

            pos = self.repo.create_position(
                token_id=signal.token_id,
                market_id=signal.market_id,
                leader_address=signal.leader_address,
                leader_trade_id=signal.leader_trade_id,
                entry_price=entry_price,
                entry_cost_usd=size,
                shares=shares,
            )
            self.repo.record_order(
                position_id=pos.id,
                token_id=signal.token_id,
                side="BUY",
                amount=size,
                clob_response=json.dumps(resp)[:4000],
                status="filled",
            )
            self.notifier.send(
                f"BUY ${size:.2f} | market={signal.market_id[:16]}... | leader={signal.leader_address[:10]}..."
            )
            log.info("position_opened", position_id=pos.id, size=size)
            return True
        except Exception as exc:
            log.error("execute_failed", error=str(exc))
            self.repo.audit("error", "execute_failed", str(exc))
            FAILED_TRADES.add(signal.leader_trade_id)
            self.notifier.send(f"Order failed: {exc}")
            return False

    def execute_manual(self, signal: CopySignal, *, dry_run: bool = False) -> tuple[bool, str]:
        """User-selected trade from dashboard; skips automatic signal filters."""
        if dry_run:
            decision = self.risk.evaluate(signal)
            if not decision.approved:
                return False, decision.reason
            self.repo.audit(
                "info",
                "manual_dry_run",
                f"{signal.leader_trade_id} ${decision.position_size_usd:.2f}",
            )
            return True, f"סימולציה: קנייה ב-${decision.position_size_usd:.2f}"
        ok = self.execute(signal, dry_run=False)
        if ok:
            return True, "עסקה בוצעה בהצלחה"
        return False, "העסקה נכשלה — ראה יומן"
