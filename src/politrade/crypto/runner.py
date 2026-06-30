"""Background runner for crypto 5m betting."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any

from politrade.api.clob_client import ClobClientWrapper
from politrade.config import AppConfig
from politrade.crypto.discovery import discover_windows
from politrade.crypto.executor import CryptoBetExecutor
from politrade.crypto.price_feed import fetch_token_prices, get_price_feed
from politrade.crypto.redemption import redeem_winning_bets, resolve_open_bets
from politrade.crypto.strategy import DecisionAction, StrategyDecision, crypto_cfg, evaluate_window
from politrade.crypto.window import WindowPhase
from politrade.execution.risk import RiskManager
from politrade.logging_setup import get_logger
from politrade.storage.repository import Repository

log = get_logger(__name__)


@dataclass
class WindowLiveState:
    window_dict: dict[str, Any]
    oracle_dict: dict[str, Any]
    tokens_dict: dict[str, Any]
    decision: dict[str, Any]
    bet_placed: bool = False


@dataclass
class RunnerState:
    windows: list[WindowLiveState] = field(default_factory=list)
    last_decisions: list[dict[str, Any]] = field(default_factory=list)
    last_error: str | None = None
    ticks: int = 0
    auto_bet: bool = True
    updated_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "windows": [
                {
                    "window": w.window_dict,
                    "oracle": w.oracle_dict,
                    "tokens": w.tokens_dict,
                    "decision": w.decision,
                    "bet_placed": w.bet_placed,
                }
                for w in self.windows
            ],
            "last_decisions": self.last_decisions[-20:],
            "last_error": self.last_error,
            "ticks": self.ticks,
            "auto_bet": self.auto_bet,
            "updated_at": self.updated_at,
            "feed": get_price_feed().status(),
        }


class CryptoRunner:
    def __init__(self, config: AppConfig | None = None) -> None:
        self._config = config
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._state = RunnerState()
        self._last_error: str | None = None
        self._ticks = 0

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "running": self.is_running,
                "ticks": self._ticks,
                "last_error": self._last_error,
                "auto_bet": self._state.auto_bet,
            }

    def get_live_state(self) -> dict[str, Any]:
        with self._lock:
            return self._state.to_dict()

    def set_auto_bet(self, enabled: bool) -> None:
        with self._lock:
            self._state.auto_bet = enabled
        repo = Repository(self._get_config())
        repo.set_state("crypto_auto_bet", "1" if enabled else "0")

    def start(self) -> None:
        if self.is_running:
            return
        get_price_feed().start()
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="crypto-runner", daemon=True)
        self._thread.start()
        log.info("crypto_runner_started")

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=30)

    def tick_once(self) -> None:
        self._single_tick()

    def _get_config(self) -> AppConfig:
        from politrade.web.user_settings import get_effective_config

        return get_effective_config()

    def _run(self) -> None:
        cfg = self._get_config()
        auto_raw = Repository(cfg).get_state("crypto_auto_bet")
        if auto_raw is not None:
            with self._lock:
                self._state.auto_bet = auto_raw == "1"
        elif not crypto_cfg(cfg).get("auto_bet", True):
            with self._lock:
                self._state.auto_bet = False

        while not self._stop.is_set():
            try:
                self._single_tick()
                self._ticks += 1
                self._last_error = None
            except Exception as exc:
                self._last_error = str(exc)
                log.error("crypto_runner_tick_failed", error=str(exc))

            cfg = self._get_config()
            ccfg = crypto_cfg(cfg)
            in_bet = any(
                w.window_dict.get("phase") == WindowPhase.BET.value
                for w in self._state.windows
            )
            wait = float(ccfg.get("poll_seconds_bet", 2) if in_bet else ccfg.get("poll_seconds_idle", 5))
            self._stop.wait(wait)

    def _single_tick(self) -> None:
        config = self._get_config()
        repo = Repository(config)
        clob = ClobClientWrapper(config)
        feed = get_price_feed()
        feed.poll_http_fallback()

        risk = RiskManager(config, repo, clob)
        if risk.is_kill_switch_active():
            return

        discovery = discover_windows(config, upcoming_count=int(crypto_cfg(config).get("upcoming_windows", 2)))
        executor = CryptoBetExecutor(config, repo, clob)

        live_windows: list[WindowLiveState] = []
        decisions: list[dict[str, Any]] = []

        for candidate in discovery.current:
            window = candidate.window
            oracle = feed.get_snapshot(window)
            snap = oracle.to_dict()
            snap["open_price"] = snap.get("open_price") or oracle.open_price
            if oracle.open_price and candidate.window.window_ts:
                bet = _find_bet(repo, window.asset.value, window.window_ts)
                if bet and bet.open_oracle_price:
                    snap["open_price"] = bet.open_oracle_price

            tokens = fetch_token_prices(clob, window)
            already = repo.has_crypto_bet_for_window(window.asset.value, window.window_ts)
            decision = evaluate_window(
                window,
                oracle,
                tokens,
                config,
                already_bet=already,
                has_liquidity_fn=clob.has_buy_liquidity if clob.is_configured else None,
            )
            dec_dict = decision.to_dict()
            dec_dict["slug"] = window.slug
            dec_dict["asset"] = window.asset.value
            decisions.append(dec_dict)

            bet_placed = already
            auto = self._state.auto_bet
            if (
                decision.action == DecisionAction.BET
                and auto
                and not already
                and clob.is_configured
            ):
                bet = executor.execute_bet(
                    window,
                    decision,
                    open_oracle_price=oracle.open_price,
                )
                if bet:
                    bet_placed = True

            live_windows.append(
                WindowLiveState(
                    window_dict=window.to_dict(),
                    oracle_dict=snap,
                    tokens_dict=tokens.to_dict(),
                    decision=dec_dict,
                    bet_placed=bet_placed,
                )
            )

        for candidate in discovery.upcoming:
            window = candidate.window
            live_windows.append(
                WindowLiveState(
                    window_dict=window.to_dict(),
                    oracle_dict={},
                    tokens_dict={},
                    decision={"action": "wait", "reason": "חלון עתידי", "slug": window.slug},
                    bet_placed=False,
                )
            )

        resolve_open_bets(config, repo)
        redeem_winning_bets(config, repo)

        with self._lock:
            self._state.windows = live_windows
            self._state.last_decisions = decisions
            self._state.ticks = self._ticks
            self._state.updated_at = time.time()
            self._state.auto_bet = self._state.auto_bet


def _find_bet(repo: Repository, asset: str, window_ts: int):
    for b in repo.list_crypto_bets(100):
        if b.asset == asset and b.window_ts == window_ts and b.status not in ("failed", "skipped"):
            return b
    return None


_runner: CryptoRunner | None = None


def get_crypto_runner() -> CryptoRunner:
    global _runner
    if _runner is None:
        _runner = CryptoRunner()
    return _runner
