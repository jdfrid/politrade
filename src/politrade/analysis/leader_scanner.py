"""Discover and scan leader traders."""

from __future__ import annotations

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

        try:
            board = self.data.get_leaderboard(limit=50)
            for entry in board:
                addr = entry.get("proxyWallet") or entry.get("address") or entry.get("user")
                if addr:
                    addresses.add(str(addr).lower())
        except Exception as exc:
            log.warning("leaderboard_fetch_failed", error=str(exc))

        return list(addresses)

    def scan(self) -> list[dict[str, Any]]:
        lookback = int(self.config.leaders.get("lookback_days", 90))
        candidates = self.discover_candidates()
        log.info("scanning_candidates", count=len(candidates))

        profiles: list[tuple[Any, str | None]] = []
        for address in candidates:
            if self._is_blacklisted(address):
                continue
            try:
                trades = self.data.get_all_trades(address, max_pages=5)
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
