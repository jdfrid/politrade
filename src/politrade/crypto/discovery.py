"""Discover active and upcoming crypto 5m windows."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from politrade.config import AppConfig
from politrade.crypto.gamma_discovery import discover_5m_windows_from_gamma, split_current_and_upcoming
from politrade.crypto.window import CryptoWindow


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
    windows = discover_5m_windows_from_gamma(cfg)
    current_raw, upcoming_raw = split_current_and_upcoming(windows)

    if upcoming_count >= 0:
        by_ts: dict[int, list[CryptoWindow]] = {}
        for w in upcoming_raw:
            by_ts.setdefault(w.window_ts, []).append(w)
        trimmed: list[CryptoWindow] = []
        for wts in sorted(by_ts.keys())[: upcoming_count + 1]:
            trimmed.extend(by_ts[wts])
        upcoming_raw = trimmed

    result = DiscoveryResult()
    for window in current_raw:
        result.current.append(_candidate(window))
    for window in upcoming_raw:
        result.upcoming.append(_candidate(window))
    return result


def _candidate(window: CryptoWindow) -> WindowCandidate:
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
