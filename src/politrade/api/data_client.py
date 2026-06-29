"""Polymarket Data API client (public, no auth)."""

from __future__ import annotations

from typing import Any

import httpx

from politrade.api.rate_limit import throttle
from politrade.config import AppConfig
from politrade.retry import with_retry


class DataClient:
    def __init__(self, config: AppConfig | None = None) -> None:
        cfg = config or AppConfig()
        api = cfg.api
        self.base_url = api.get("data_base_url", "https://data-api.polymarket.com").rstrip("/")
        self.gamma_url = api.get("gamma_base_url", "https://gamma-api.polymarket.com").rstrip("/")
        self.timeout = float(api.get("request_timeout", 30))
        self.max_retries = int(api.get("max_retries", 3))
        self._retry_base = float(api.get("retry_base_delay", 2.0))
        self._client = httpx.Client(timeout=self.timeout)

    def _get(self, url: str, params: dict[str, Any] | None = None) -> Any:
        def _request():
            throttle()
            resp = self._client.get(url, params=params)
            resp.raise_for_status()
            return resp.json()

        return with_retry(
            _request,
            max_retries=self.max_retries,
            base_delay=self._retry_base,
        )

    def get_leaderboard(
        self,
        *,
        category: str = "OVERALL",
        time_period: str = "MONTH",
        order_by: str = "PNL",
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        data = self._get(
            f"{self.base_url}/v1/leaderboard",
            {
                "category": category,
                "timePeriod": time_period,
                "orderBy": order_by,
                "limit": limit,
                "offset": offset,
            },
        )
        if isinstance(data, list):
            return data
        return data.get("data", data.get("leaderboard", []))

    def get_leaderboard_multi(
        self,
        *,
        periods: list[str] | None = None,
        limit: int = 25,
    ) -> list[dict[str, Any]]:
        """Merge unique traders from multiple leaderboard time periods."""
        if periods is None:
            periods = ["DAY", "WEEK", "MONTH"]
        seen: set[str] = set()
        merged: list[dict[str, Any]] = []
        for period in periods:
            try:
                board = self.get_leaderboard(time_period=period, limit=limit)
            except httpx.HTTPError:
                continue
            for entry in board:
                addr = entry.get("proxyWallet") or entry.get("address") or entry.get("user")
                if not addr:
                    continue
                key = str(addr).lower()
                if key in seen:
                    continue
                seen.add(key)
                merged.append(entry)
        return merged

    def get_trending_markets(self, *, limit: int = 10) -> list[dict[str, Any]]:
        data = self._get(
            f"{self.gamma_url}/markets",
            {
                "active": "true",
                "closed": "false",
                "order": "volume24hr",
                "ascending": "false",
                "limit": limit,
            },
        )
        if isinstance(data, list):
            return data
        return data.get("data", data.get("markets", []))

    def get_trades(
        self,
        user: str | None = None,
        *,
        limit: int = 100,
        offset: int = 0,
        market: str | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if user:
            params["user"] = user
        if market:
            params["market"] = market
        data = self._get(f"{self.base_url}/trades", params)
        if isinstance(data, list):
            return data
        return data.get("data", data.get("trades", []))

    def get_all_trades(self, user: str, *, max_pages: int = 10, page_size: int = 100) -> list[dict[str, Any]]:
        all_trades: list[dict[str, Any]] = []
        offset = 0
        for _ in range(max_pages):
            batch = self.get_trades(user, limit=page_size, offset=offset)
            if not batch:
                break
            all_trades.extend(batch)
            if len(batch) < page_size:
                break
            offset += page_size
        return all_trades

    def get_positions(self, user: str, *, limit: int = 100) -> list[dict[str, Any]]:
        data = self._get(
            f"{self.base_url}/positions",
            {"user": user, "limit": limit},
        )
        if isinstance(data, list):
            return data
        return data.get("data", data.get("positions", []))

    def get_market(self, condition_id: str) -> dict[str, Any] | None:
        try:
            markets = self._get(
                f"{self.gamma_url}/markets",
                {"condition_ids": condition_id},
            )
            if isinstance(markets, list) and markets:
                return markets[0]
            if isinstance(markets, dict):
                items = markets.get("data", [])
                return items[0] if items else None
        except httpx.HTTPError:
            return None
        return None

    def get_market_by_slug(self, slug: str) -> dict[str, Any] | None:
        try:
            data = self._get(f"{self.gamma_url}/markets/slug/{slug}")
            if isinstance(data, dict) and data:
                return data
        except httpx.HTTPError:
            return None
        return None

    def close(self) -> None:
        self._client.close()
