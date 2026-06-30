"""Background simulation runner for crypto 5m — no CLOB orders."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any

from politrade.api.clob_client import ClobClientWrapper
from politrade.config import AppConfig
from politrade.crypto.cycle_summary import build_cycle_summary
from politrade.crypto.discovery import discover_windows
from politrade.crypto.gamma_discovery import discover_5m_windows_from_gamma
from politrade.crypto.learner import run_learner_after_cycle
from politrade.crypto.price_feed import fetch_token_prices, get_price_feed
from politrade.crypto.sim_engine import execute_sim_bet, resolve_sim_bets_for_window
from politrade.crypto.sim_mode import is_live_enabled
from politrade.crypto.sizing import entry_timing_label, recommend_bet_usd, worth_investing
from politrade.crypto.strategy import DecisionAction, crypto_cfg, evaluate_window
from politrade.crypto.window import WindowPhase, compute_window_ts
from politrade.logging_setup import get_logger
from politrade.storage.repository import Repository

log = get_logger(__name__)


@dataclass
class SimMarketState:
    window_dict: dict[str, Any]
    oracle_dict: dict[str, Any]
    tokens_dict: dict[str, Any]
    decision: dict[str, Any]
    recommended_usd: float
    entry_timing: str
    worth_investing: bool
    bet_placed: bool
    bet_status: str | None = None


@dataclass
class SimRunnerState:
    markets: list[SimMarketState] = field(default_factory=list)
    current_window_ts: int = 0
    auto_sim: bool = True
    last_closed_window_ts: int | None = None
    ticks: int = 0
    last_error: str | None = None
    updated_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "markets": [
                {
                    "window": m.window_dict,
                    "oracle": m.oracle_dict,
                    "tokens": m.tokens_dict,
                    "decision": m.decision,
                    "recommended_usd": m.recommended_usd,
                    "entry_timing": m.entry_timing,
                    "worth_investing": m.worth_investing,
                    "bet_placed": m.bet_placed,
                    "bet_status": m.bet_status,
                }
                for m in self.markets
            ],
            "current_window_ts": self.current_window_ts,
            "auto_sim": self.auto_sim,
            "ticks": self.ticks,
            "last_error": self.last_error,
            "updated_at": self.updated_at,
        }


class SimRunner:
    def __init__(self, config: AppConfig | None = None) -> None:
        self._config = config
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._state = SimRunnerState()
        self._ticks = 0
        self._last_error: str | None = None

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
                "auto_sim": self._state.auto_sim,
            }

    def get_live_state(self) -> dict[str, Any]:
        with self._lock:
            return self._state.to_dict()

    def set_auto_sim(self, enabled: bool) -> None:
        with self._lock:
            self._state.auto_sim = enabled
        repo = Repository(self._get_config())
        repo.set_state("sim_auto_run", "1" if enabled else "0")

    def start(self) -> None:
        if self.is_running:
            return
        get_price_feed().start()
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="sim-runner", daemon=True)
        self._thread.start()
        log.info("sim_runner_started")

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
        repo = Repository(self._get_config())
        auto_raw = repo.get_state("sim_auto_run")
        if auto_raw is not None:
            with self._lock:
                self._state.auto_sim = auto_raw == "1"

        while not self._stop.is_set():
            try:
                self._single_tick()
                self._ticks += 1
                self._last_error = None
            except Exception as exc:
                self._last_error = str(exc)
                log.error("sim_runner_tick_failed", error=str(exc))

            cfg = self._get_config()
            ccfg = crypto_cfg(cfg)
            with self._lock:
                in_bet = any(
                    m.window_dict.get("phase") == WindowPhase.BET.value
                    for m in self._state.markets
                )
            wait = float(ccfg.get("poll_seconds_bet", 2) if in_bet else ccfg.get("poll_seconds_idle", 5))
            self._stop.wait(wait)

    def _single_tick(self) -> None:
        config = self._get_config()
        repo = Repository(config)
        feed = get_price_feed()
        feed.poll_http_fallback()

        now_wts = compute_window_ts()
        with self._lock:
            prev_wts = self._state.current_window_ts

        if prev_wts and prev_wts != now_wts:
            self._close_cycle(prev_wts, config, repo)

        clob = ClobClientWrapper(config)
        ccfg = crypto_cfg(config)
        balance = repo.get_sim_balance()

        windows = discover_5m_windows_from_gamma(config)
        current = [w for w in windows if w.window_ts == now_wts]
        if not current:
            discovery = discover_windows(config, upcoming_count=0)
            current = [c.window for c in discovery.current]

        market_states: list[SimMarketState] = []

        for window in current:
            oracle = feed.get_snapshot(window)
            snap = oracle.to_dict()
            tokens = fetch_token_prices(clob, window) if clob.is_configured else _tokens_empty()
            already = repo.has_sim_bet_for_window(window.asset.value, window.window_ts)

            decision = evaluate_window(
                window,
                oracle,
                tokens,
                config,
                already_bet=already,
                has_liquidity_fn=clob.has_buy_liquidity if clob.is_configured else None,
            )

            phase = window.phase()
            secs = window.seconds_elapsed()
            timing = entry_timing_label(phase.value, secs, ccfg)
            rec_usd = recommend_bet_usd(decision, balance, ccfg)
            wi = worth_investing(decision)

            dec_dict = decision.to_dict()
            dec_dict["slug"] = window.slug
            dec_dict["asset"] = window.asset.value

            repo.upsert_sim_decision(
                asset=window.asset.value,
                window_ts=window.window_ts,
                slug=window.slug,
                action=decision.action.value,
                side=decision.side.value if decision.side else None,
                reason=decision.reason,
                phase=phase.value,
                entry_ask=decision.entry_ask,
                edge_pct=decision.edge_pct,
                recommended_usd=rec_usd,
                confidence=decision.confidence,
                oracle_delta_pct=oracle.delta_pct,
                entry_timing=timing,
                worth_investing=wi,
            )

            bet_placed = already
            bet_status = None
            if already:
                for b in repo.get_sim_bets_for_window(window.window_ts):
                    if b.asset == window.asset.value:
                        bet_status = b.status
                        break

            auto = self._state.auto_sim
            with self._lock:
                auto = self._state.auto_sim

            if auto and decision.action == DecisionAction.BET and not already:
                bet = execute_sim_bet(
                    repo,
                    window,
                    decision,
                    bet_usd=rec_usd,
                    open_oracle_price=oracle.open_price,
                )
                if bet:
                    bet_placed = True
                    bet_status = "open"
                    balance = repo.get_sim_balance()

            market_states.append(
                SimMarketState(
                    window_dict=window.to_dict(),
                    oracle_dict=snap,
                    tokens_dict=tokens.to_dict(),
                    decision=dec_dict,
                    recommended_usd=rec_usd,
                    entry_timing=timing,
                    worth_investing=wi,
                    bet_placed=bet_placed,
                    bet_status=bet_status,
                )
            )

        upcoming = [w for w in windows if w.window_ts > now_wts][:14]
        for window in upcoming:
            market_states.append(
                SimMarketState(
                    window_dict=window.to_dict(),
                    oracle_dict={},
                    tokens_dict={},
                    decision={"action": "wait", "reason": "חלון עתידי", "slug": window.slug},
                    recommended_usd=0.0,
                    entry_timing="עתידי",
                    worth_investing=False,
                    bet_placed=False,
                )
            )

        if is_live_enabled(repo):
            from politrade.crypto.runner import get_crypto_runner
            get_crypto_runner().tick_once()

        with self._lock:
            self._state.markets = market_states
            self._state.current_window_ts = now_wts
            self._state.ticks = self._ticks
            self._state.updated_at = time.time()

    def _close_cycle(self, window_ts: int, config: AppConfig, repo: Repository) -> None:
        resolve_sim_bets_for_window(window_ts, config, repo)
        cycle = build_cycle_summary(window_ts, config, repo)
        if cycle:
            run_learner_after_cycle(cycle, config, repo)
        with self._lock:
            self._state.last_closed_window_ts = window_ts
        log.info("sim_cycle_closed", window_ts=window_ts)


def _tokens_empty():
    from politrade.crypto.price_feed import TokenPrices

    return TokenPrices()


_runner: SimRunner | None = None


def get_sim_runner() -> SimRunner:
    global _runner
    if _runner is None:
        _runner = SimRunner()
    return _runner
