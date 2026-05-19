"""Pre-trade risk checks."""

from __future__ import annotations

import os
from dataclasses import dataclass

from politrade.api.clob_client import ClobClientWrapper
from politrade.config import AppConfig
from politrade.signals.trade_selector import CopySignal
from politrade.storage.repository import Repository


@dataclass
class RiskDecision:
    approved: bool
    position_size_usd: float = 0.0
    reason: str = ""


class RiskManager:
    def __init__(
        self,
        config: AppConfig | None = None,
        repo: Repository | None = None,
        clob: ClobClientWrapper | None = None,
    ) -> None:
        self.config = config or AppConfig()
        self.repo = repo or Repository(self.config)
        self.clob = clob or ClobClientWrapper(self.config)

    def is_kill_switch_active(self) -> bool:
        if os.environ.get("KILL_SWITCH", "").lower() in ("1", "true", "yes"):
            return True
        if self.config.kill_switch_path.exists():
            return True
        return self.repo.get_state("kill_switch") == "1"

    def evaluate(self, signal: CopySignal) -> RiskDecision:
        if self.is_kill_switch_active():
            return RiskDecision(False, reason="kill_switch_active")

        risk = self.config.risk
        copy = self.config.copy

        max_pos = float(risk.get("max_position_usd", 50))
        copy_ratio = float(copy.get("copy_ratio", 0.1))
        max_exposure = float(risk.get("max_total_exposure_usd", 200))
        max_open = int(risk.get("max_open_positions", 5))

        size = min(max_pos, signal.leader_size_usd * copy_ratio)
        if size < 1.0:
            return RiskDecision(False, reason="position_too_small")

        if self.repo.count_open_positions() >= max_open:
            return RiskDecision(False, reason="max_open_positions")

        if self.repo.total_open_exposure() + size > max_exposure:
            return RiskDecision(False, reason="max_total_exposure")

        if self.clob.is_configured:
            balance = self.clob.get_balance()
            if balance is not None and balance < size:
                return RiskDecision(False, reason="insufficient_balance")

        return RiskDecision(True, position_size_usd=size)
