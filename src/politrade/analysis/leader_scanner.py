"""Discover and scan leader traders."""

from __future__ import annotations

import json
from typing import Any

from politrade.analysis.leader_ranker import rank_traders
from politrade.analysis.metrics import compute_metrics
from politrade.api.data_client import DataClient
from politrade.config import AppConfig
from politrade.logging_setup import get_logger
from politrade.storage.repository import Repository

log = get_logger(__name__)


class LeaderScanner:
    def __init__(
        self,
        config: AppConfig | None = None,
        data: DataClient | None = None,
        repo: Repository | None = None,
    ) -> None:
        self.config = config or AppConfig()
        self.data = data or DataClient(self.config)
        self.repo = repo or Repository(self.config)

    def discover_candidates(self) -> list[str]:
        addresses: set[str] = set()
        manual = self.config.leaders.get("manual_leaders", []) or []
        addresses.update(a.lower() for a in manual)

        limit = int(self.config.leaders.get("scan_leaderboard_limit", 15))
        try:
            board = self.data.get_leaderboard(limit=limit)
            self._seed_leaderboard(board)
            for entry in board:
                addr = entry.get("proxyWallet") or entry.get("address") or entry.get("user")
                if addr:
                    addresses.add(str(addr).lower())
        except Exception as exc:
            log.warning("leaderboard_fetch_failed", error=str(exc))

        return list(addresses)

    def _seed_leaderboard(self, board: list[dict[str, Any]]) -> None:
        """Upsert leaderboard traders immediately so the UI is not empty during scan."""
        top_k = int(self.config.leaders.get("display_top_k", 5))
        for i, entry in enumerate(board[:top_k]):
            addr = entry.get("proxyWallet") or entry.get("address") or entry.get("user")
            if not addr:
                continue
            username = entry.get("userName") or entry.get("name") or entry.get("pseudonym")
            placeholder_score = max(55.0, 88.0 - i * 6.0)
            self.repo.upsert_trader(
                str(addr).lower(),
                username=str(username) if username else None,
                score=placeholder_score,
                is_active_leader=False,
            )

    def _set_progress(
        self,
        *,
        running: bool,
        done: int = 0,
        total: int = 0,
        phase: str = "scanning",
        leaders: int = 0,
        error: str | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "running": running,
            "done": done,
            "total": total,
            "phase": phase,
            "leaders": leaders,
        }
        if error:
            payload["error"] = error
        self.repo.set_state("scan_progress", json.dumps(payload))

    def scan(self) -> list[dict[str, Any]]:
        lookback = int(self.config.leaders.get("lookback_days", 90))
        max_pages = int(self.config.leaders.get("scan_max_trade_pages", 2))
        candidates = self.discover_candidates()
        total = len(candidates)
        log.info("scanning_candidates", count=total)
        self._set_progress(running=True, done=0, total=total, phase="starting")

        profiles: list[tuple[Any, str | None]] = []
        for idx, address in enumerate(candidates):
            self._set_progress(running=True, done=idx, total=total, phase="scanning")
            if self._is_blacklisted(address):
                continue
            try:
                trades = self.data.get_all_trades(address, max_pages=max_pages)
                metrics = compute_metrics(address, trades, lookback_days=lookback)
                username = self._username_from_trades(trades)
                profiles.append((metrics, username))
                self.repo.upsert_trader(
                    address,
                    username=username,
                    score=0.0,
                    metrics=metrics.to_dict(),
                    is_active_leader=False,
                )
            except Exception as exc:
                log.warning("scan_trader_failed", address=address, error=str(exc))

        ranked = rank_traders(profiles, self.config)
        leader_addrs = [r["address"] for r in ranked]
        self.repo.set_active_leaders(leader_addrs)

        for r in ranked:
            self.repo.upsert_trader(
                r["address"],
                username=r.get("username"),
                score=r["score"],
                metrics=r["metrics"],
                is_active_leader=True,
            )

        self._set_progress(
            running=False,
            done=total,
            total=total,
            phase="done",
            leaders=len(ranked),
        )
        log.info("scan_complete", leaders=len(ranked))
        return ranked

    def _is_blacklisted(self, address: str) -> bool:
        with self.repo.session() as s:
            from politrade.storage.models import Trader

            t = s.get(Trader, address.lower())
            return t is not None and t.is_blacklisted

    @staticmethod
    def _username_from_trades(trades: list[dict]) -> str | None:
        for t in trades:
            name = t.get("name") or t.get("username") or t.get("pseudonym")
            if name:
                return str(name)
        return None
