"""Background monitor for open positions — prices, snapshots, auto-exit."""

from __future__ import annotations

import threading
import time
from typing import Any

from politrade.api.clob_client import ClobClientWrapper
from politrade.config import AppConfig
from politrade.execution.exit_monitor import ExitMonitor
from politrade.execution.position_valuation import ExitTargets, value_position
from politrade.execution.risk import RiskManager
from politrade.logging_setup import get_logger
from politrade.storage.repository import Repository

log = get_logger(__name__)

IDLE_SLEEP_SECONDS = 60


class PositionMonitor:
    """Always-on thread: refresh prices, record snapshots, trigger exits."""

    def __init__(self, config: AppConfig | None = None) -> None:
        self._config = config
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_error: str | None = None
        self._ticks = 0

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def status(self) -> dict[str, Any]:
        return {
            "running": self.is_running,
            "ticks": self._ticks,
            "last_error": self._last_error,
        }

    def start(self) -> None:
        if self.is_running:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="politrade-position-monitor",
            daemon=True,
        )
        self._thread.start()
        log.info("position_monitor_started")

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=30)
        log.info("position_monitor_stopped")

    def tick_once(self) -> None:
        self._single_tick()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._single_tick()
                self._ticks += 1
                self._last_error = None
            except Exception as exc:
                self._last_error = str(exc)
                log.error("position_monitor_tick_failed", error=str(exc))
            interval = self._monitor_interval()
            open_count = len(Repository(self._get_config()).get_open_positions())
            wait = interval if open_count else IDLE_SLEEP_SECONDS
            self._stop.wait(wait)

    def _get_config(self) -> AppConfig:
        from politrade.web.user_settings import get_effective_config

        return get_effective_config()

    def _monitor_interval(self) -> int:
        cfg = self._get_config()
        return int(cfg.exit.get("monitor_seconds", 20))

    def _single_tick(self) -> None:
        config = self._get_config()
        repo = Repository(config)
        clob = ClobClientWrapper(config)
        risk = RiskManager(config, repo, clob)
        if risk.is_kill_switch_active():
            return

        positions = repo.get_open_positions()
        if not positions:
            return

        exit_mon = ExitMonitor(config, repo, clob)
        targets = ExitTargets.from_config(config.exit)

        for pos in positions:
            price = exit_mon._fetch_price(pos)
            valuation = value_position(pos, price, targets=targets)
            repo.record_snapshot(
                pos.id,
                price=valuation.current_price,
                value_usd=valuation.current_value_usd,
                pnl_usd=valuation.pnl_usd,
                pnl_pct=valuation.pnl_pct,
            )
            exit_mon.check_position(pos, targets=targets, dry_run=False, price=price)

        repo.prune_snapshots(max_age_hours=48)


_monitor: PositionMonitor | None = None


def get_position_monitor() -> PositionMonitor:
    global _monitor
    if _monitor is None:
        _monitor = PositionMonitor()
    return _monitor
