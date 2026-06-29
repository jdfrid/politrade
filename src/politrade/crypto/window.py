"""5-minute crypto window timing and market parsing."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from politrade.api.data_client import DataClient
from politrade.config import AppConfig

WINDOW_SECONDS = 300


class CryptoAsset(str, Enum):
    BTC = "btc"
    ETH = "eth"
    SOL = "sol"
    XRP = "xrp"

    @property
    def chainlink_pair(self) -> str:
        return f"{self.value}/usd"

    @property
    def label(self) -> str:
        return self.value.upper()


class WindowPhase(str, Enum):
    EARLY = "early"
    BET = "bet"
    LATE = "late"
    CLOSED = "closed"


class BetSide(str, Enum):
    UP = "up"
    DOWN = "down"


@dataclass
class TokenPair:
    up_token_id: str
    down_token_id: str


@dataclass
class CryptoWindow:
    asset: CryptoAsset
    window_ts: int
    slug: str
    condition_id: str = ""
    title: str = ""
    up_token_id: str = ""
    down_token_id: str = ""
    closed: bool = False
    active: bool = True
    end_date: str = ""

    @property
    def window_end_ts(self) -> int:
        return self.window_ts + WINDOW_SECONDS

    def phase(self, now: float | None = None) -> WindowPhase:
        ts = now if now is not None else time.time()
        if ts >= self.window_end_ts:
            return WindowPhase.CLOSED
        elapsed = int(ts) - self.window_ts
        cfg = _phase_cfg()
        if elapsed < cfg["no_bet_first_seconds"]:
            return WindowPhase.EARLY
        if elapsed >= WINDOW_SECONDS - cfg["no_bet_last_seconds"]:
            return WindowPhase.LATE
        return WindowPhase.BET

    def seconds_elapsed(self, now: float | None = None) -> int:
        ts = now if now is not None else time.time()
        return max(0, min(WINDOW_SECONDS, int(ts) - self.window_ts))

    def seconds_remaining(self, now: float | None = None) -> int:
        ts = now if now is not None else time.time()
        return max(0, self.window_end_ts - int(ts))

    def to_dict(self) -> dict[str, Any]:
        now = time.time()
        phase = self.phase(now)
        return {
            "asset": self.asset.value,
            "asset_label": self.asset.label,
            "window_ts": self.window_ts,
            "window_end_ts": self.window_end_ts,
            "slug": self.slug,
            "condition_id": self.condition_id,
            "title": self.title,
            "up_token_id": self.up_token_id,
            "down_token_id": self.down_token_id,
            "closed": self.closed,
            "active": self.active,
            "phase": phase.value,
            "seconds_elapsed": self.seconds_elapsed(now),
            "seconds_remaining": self.seconds_remaining(now),
        }


_phase_cfg_cache: dict[str, int] | None = None


def _phase_cfg() -> dict[str, int]:
    global _phase_cfg_cache
    if _phase_cfg_cache is None:
        from politrade.config import AppConfig

        cfg = AppConfig().crypto
        _phase_cfg_cache = {
            "no_bet_first_seconds": int(cfg.get("no_bet_first_seconds", 120)),
            "no_bet_last_seconds": int(cfg.get("no_bet_last_seconds", 60)),
        }
    return _phase_cfg_cache


def reset_phase_cfg_cache() -> None:
    global _phase_cfg_cache
    _phase_cfg_cache = None


def compute_window_ts(now: float | None = None) -> int:
    ts = int(now if now is not None else time.time())
    return (ts // WINDOW_SECONDS) * WINDOW_SECONDS


def build_slug(asset: CryptoAsset, window_ts: int) -> str:
    return f"{asset.value}-updown-5m-{window_ts}"


def parse_token_ids(market: dict[str, Any]) -> TokenPair | None:
    raw = market.get("clobTokenIds")
    if raw is None:
        return None
    if isinstance(raw, str):
        try:
            ids = json.loads(raw)
        except json.JSONDecodeError:
            return None
    else:
        ids = raw
    if not isinstance(ids, list) or len(ids) < 2:
        return None
    return TokenPair(up_token_id=str(ids[0]), down_token_id=str(ids[1]))


def parse_market(asset: CryptoAsset, window_ts: int, market: dict[str, Any]) -> CryptoWindow | None:
    tokens = parse_token_ids(market)
    if tokens is None:
        return None
    slug = build_slug(asset, window_ts)
    return CryptoWindow(
        asset=asset,
        window_ts=window_ts,
        slug=slug,
        condition_id=str(market.get("conditionId") or market.get("condition_id") or ""),
        title=str(market.get("question") or market.get("title") or slug),
        up_token_id=tokens.up_token_id,
        down_token_id=tokens.down_token_id,
        closed=bool(market.get("closed")),
        active=market.get("active", True) is not False,
        end_date=str(market.get("endDate") or market.get("end_date") or ""),
    )


def fetch_window_market(
    asset: CryptoAsset,
    window_ts: int,
    *,
    config: AppConfig | None = None,
    data: DataClient | None = None,
) -> CryptoWindow | None:
    slug = build_slug(asset, window_ts)
    client = data or DataClient(config)
    own_client = data is None
    try:
        market = client.get_market_by_slug(slug)
        if not market:
            return None
        return parse_market(asset, window_ts, market)
    finally:
        if own_client:
            client.close()


def enabled_assets(config: AppConfig | None = None) -> list[CryptoAsset]:
    from politrade.config import AppConfig

    cfg = config or AppConfig()
    raw = cfg.crypto.get("assets", ["btc"])
    assets: list[CryptoAsset] = []
    for item in raw:
        try:
            assets.append(CryptoAsset(str(item).lower()))
        except ValueError:
            continue
    return assets or [CryptoAsset.BTC]
