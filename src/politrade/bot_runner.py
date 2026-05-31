"""Background trading loop controllable from CLI or web UI."""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from typing import Any, Literal

from politrade.analysis.leader_scanner import LeaderScanner
from politrade.api.data_client import DataClient
from politrade.config import AppConfig, get_config
from politrade.execution.order_executor import OrderExecutor
from politrade.logging_setup import get_logger
from politrade.signals.copy_detector import CopyDetector
from politrade.storage.repository import Repository

log = get_logger(__name__)
Mode = Literal["watch", "trade"]


def should_rescan(config: AppConfig, repo: Repository) -> bool:
    last = repo.get_state("last_leader_scan")
    if not last:
        return True
    try:
        last_dt = datetime.fromisoformat(last)
        if last_dt.tzinfo is None:
            last_dt = last_dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return True
    hours = int(config.leaders.get("rescan_hours", 12))
    elapsed = (datetime.now(timezone.utc) - last_dt).total_seconds() / 3600
    return elapsed >= hours


class BotRunner:
    """Thread-safe bot loop for web dashboard and CLI."""

    def __init__(self, config: AppConfig | None = None) -> None:
        from politrade.web.user_settings import get_effective_config

        self.config = config or get_effective_config()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._mode: Mode = "watch"
        self._last_error: str | None = None
        self._iterations = 0
        self._scan_thread: threading.Thread | None = None

    @property
    def scan_running(self) -> bool:
        return self._scan_thread is not None and self._scan_thread.is_alive()

    def scan_status(self) -> dict[str, Any]:
        repo = Repository(self.config)
        raw = repo.get_state("scan_progress")
        if not raw:
            return {"running": self.scan_running, "done": 0, "total": 0, "phase": "idle", "leaders": 0}
        try:
            data = json.loads(raw)
            data["running"] = self.scan_running or bool(data.get("running"))
            return data
        except (json.JSONDecodeError, TypeError):
            return {"running": self.scan_running, "done": 0, "total": 0, "phase": "idle", "leaders": 0}

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def mode(self) -> Mode:
        return self._mode

    @property
    def status(self) -> dict:
        return {
            "running": self.is_running,
            "mode": self._mode,
            "iterations": self._iterations,
            "last_error": self._last_error,
        }

    def start(self, mode: Mode) -> bool:
        if self.is_running:
            return False
        self._mode = mode
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="politrade-bot", daemon=True)
        self._thread.start()
        Repository(self.config).set_state("bot_mode", mode)
        Repository(self.config).audit("info", "bot_started", f"mode={mode}")
        return True

    def stop(self) -> bool:
        if not self.is_running:
            return False
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=120)
        Repository(self.config).audit("info", "bot_stopped", "")
        return True

    def run_scan_once(self) -> list[dict]:
        from politrade.web.user_settings import get_effective_config

        self.config = get_effective_config()
        scanner = LeaderScanner(self.config)
        return scanner.scan()

    def start_scan_async(self) -> bool:
        """Start leader scan in background; returns False if already running."""
        if self.scan_running:
            return False
        self._scan_thread = threading.Thread(
            target=self._run_scan_background,
            name="politrade-scan",
            daemon=True,
        )
        self._scan_thread.start()
        return True

    def _run_scan_background(self) -> None:
        repo = Repository(self.config)
        repo.audit("info", "scan_started", "background")
        try:
            ranked = self.run_scan_once()
            repo.set_state(
                "last_leader_scan",
                datetime.now(timezone.utc).isoformat(),
            )
            repo.audit("info", "scan_complete", f"leaders={len(ranked)}")
        except Exception as exc:
            log.error("scan_failed", error=str(exc))
            repo.audit("error", "scan_failed", str(exc))
            repo.set_state(
                "scan_progress",
                json.dumps(
                    {
                        "running": False,
                        "done": 0,
                        "total": 0,
                        "phase": "error",
                        "leaders": 0,
                        "error": str(exc),
                    }
                ),
            )

    def run_iteration_once(self, mode: Mode) -> None:
        self._mode = mode
        self._single_iteration()

    def _run(self) -> None:
        log.info("bot_loop_started", mode=self._mode)
        poll_seconds = int(self.config.copy.get("poll_seconds", 45))
        while not self._stop.is_set():
            try:
                self._single_iteration()
                self._iterations += 1
                self._last_error = None
            except Exception as exc:
                self._last_error = str(exc)
                log.error("bot_iteration_failed", error=str(exc))
                Repository(self.config).audit("error", "iteration_failed", str(exc))
            self._stop.wait(poll_seconds)
        log.info("bot_loop_stopped")

    def _single_iteration(self) -> None:
        from politrade.web.user_settings import get_effective_config

        self.config = get_effective_config()
        repo = Repository(self.config)
        data = DataClient(self.config)
        try:
            if should_rescan(self.config, repo):
                LeaderScanner(self.config, data, repo).scan()
                repo.set_state("last_leader_scan", datetime.now(timezone.utc).isoformat())

            dry_run = self._mode == "watch"
            detector = CopyDetector(self.config, data, repo)
            executor = OrderExecutor(self.config, repo)

            signals = detector.poll()
            for sig in signals:
                executor.execute(sig, dry_run=dry_run)

        finally:
            data.close()


_runner: BotRunner | None = None


def get_bot_runner() -> BotRunner:
    global _runner
    if _runner is None:
        _runner = BotRunner()
    return _runner
