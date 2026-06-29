"""Discover active and upcoming crypto 5m windows."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from politrade.api.data_client import DataClient
from politrade.config import AppConfig
from politrade.crypto.window import (
    CryptoAsset,
    CryptoWindow,
    compute_window_ts,
    enabled_assets,
    fetch_window_market,
)


@dataclass
class WindowCandidate:
    window: CryptoWindow
    tradable: bool = False
    skip_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = self.window.to_dict()
        d["tradable"] = self.tradable
        d["skip_reason"] = self.skip_reason
        return d


@dataclass
class DiscoveryResult:
    current: list[WindowCandidate] = field(default_factory=list)
    upcoming: list[WindowCandidate] = field(default_factory=list)

    def all_windows(self) -> list[WindowCandidate]:
        return self.current + self.upcoming

    def to_dict(self) -> dict[str, Any]:
        return {
            "current": [c.to_dict() for c in self.current],
            "upcoming": [c.to_dict() for c in self.upcoming],
        }


def discover_windows(
    config: AppConfig | None = None,
    *,
    upcoming_count: int = 2,
) -> DiscoveryResult:
    from politrade.config import AppConfig

    cfg = config or AppConfig()
    assets = enabled_assets(cfg)
    now_ts = compute_window_ts()
    data = DataClient(cfg)
    result = DiscoveryResult()

    try:
        for asset in assets:
            current = _load_candidate(asset, now_ts, data, cfg)
            if current:
                result.current.append(current)
            for i in range(1, upcoming_count + 1):
                wts = now_ts + i * 300
                upcoming = _load_candidate(asset, wts, data, cfg)
                if upcoming:
                    result.upcoming.append(upcoming)
    finally:
        data.close()

    return result


def _load_candidate(
    asset: CryptoAsset,
    window_ts: int,
    data: DataClient,
    config: AppConfig,
) -> WindowCandidate | None:
    window = fetch_window_market(asset, window_ts, config=config, data=data)
    if window is None:
        return None
    tradable = True
    reason = ""
    if window.closed:
        tradable = False
        reason = "שוק נסגר"
    elif not window.active:
        tradable = False
        reason = "שוק לא פעיל"
    elif not window.up_token_id or not window.down_token_id:
        tradable = False
        reason = "חסרים token IDs"
    return WindowCandidate(window=window, tradable=tradable, skip_reason=reason)
