"""Discover crypto 5m windows from Polymarket Gamma (tag 5M)."""

from __future__ import annotations

import time
from typing import Any

from politrade.api.data_client import DataClient
from politrade.config import AppConfig
from politrade.crypto.strategy import crypto_cfg
from politrade.crypto.window import (
    CryptoWindow,
    compute_window_ts,
    parse_market_from_slug,
    parse_slug_parts,
)
from politrade.logging_setup import get_logger

log = get_logger(__name__)

_TAG_5M = "5M"
_CACHE: tuple[float, list[CryptoWindow]] | None = None
_CACHE_TTL = 25.0


def invalidate_gamma_cache() -> None:
    global _CACHE
    _CACHE = None


def fetch_5m_events(
    data: DataClient,
    *,
    max_events: int = 400,
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    offset = 0
    page_size = 100
    while len(events) < max_events:
        batch = data.get_events_by_tag(
            _TAG_5M,
            active=True,
            closed=False,
            limit=min(page_size, max_events - len(events)),
            offset=offset,
        )
        if not batch:
            break
        events.extend(batch)
        if len(batch) < page_size:
            break
        offset += page_size
    return events


def parse_event_to_window(event: dict[str, Any]) -> CryptoWindow | None:
    slug = str(event.get("slug") or "")
    if not parse_slug_parts(slug):
        return None
    markets = event.get("markets") or []
    market = markets[0] if markets else None
    if not isinstance(market, dict) or not market:
        return None
    window = parse_market_from_slug(slug, market)
    if window is None:
        return None
    if event.get("closed") is True:
        window.closed = True
    if event.get("active") is False:
        window.active = False
    title = event.get("title") or event.get("question")
    if title:
        window.title = str(title)
    return window


def discover_5m_windows_from_gamma(
    config: AppConfig | None = None,
    *,
    data: DataClient | None = None,
    markets_ahead: int | None = None,
    use_cache: bool = True,
) -> list[CryptoWindow]:
    global _CACHE
    from politrade.config import AppConfig

    cfg = config or AppConfig()
    ccfg = crypto_cfg(cfg)
    ahead = int(markets_ahead if markets_ahead is not None else ccfg.get("markets_ahead", 4))
    now = time.time()
    now_wts = compute_window_ts(now)
    max_wts = now_wts + ahead * 300

    if use_cache and _CACHE and now - _CACHE[0] < _CACHE_TTL:
        cached = _CACHE[1]
        return _filter_windows(cached, now=now, now_wts=now_wts, max_wts=max_wts)

    own_client = data is None
    client = data or DataClient(cfg)
    windows: list[CryptoWindow] = []
    seen: set[str] = set()

    try:
        events = fetch_5m_events(client)
        for event in events:
            window = parse_event_to_window(event)
            if window is None:
                continue
            if window.slug in seen:
                continue
            seen.add(window.slug)
            windows.append(window)
    except Exception as exc:
        log.warning("gamma_5m_fetch_failed", error=str(exc))
    finally:
        if own_client:
            client.close()

    windows.sort(key=lambda w: (w.window_ts, w.asset.value))
    _CACHE = (now, windows)
    return _filter_windows(windows, now=now, now_wts=now_wts, max_wts=max_wts)


def _filter_windows(
    windows: list[CryptoWindow],
    *,
    now: float,
    now_wts: int,
    max_wts: int,
) -> list[CryptoWindow]:
    out: list[CryptoWindow] = []
    for w in windows:
        if w.closed:
            continue
        if w.window_end_ts <= int(now):
            continue
        if w.window_ts > max_wts:
            continue
        if w.window_ts < now_wts:
            continue
        out.append(w)
    return out


def split_current_and_upcoming(
    windows: list[CryptoWindow],
    *,
    now: float | None = None,
) -> tuple[list[CryptoWindow], list[CryptoWindow]]:
    now_wts = compute_window_ts(now)
    current = [w for w in windows if w.window_ts == now_wts]
    upcoming = sorted(
        [w for w in windows if w.window_ts > now_wts],
        key=lambda w: (w.window_ts, w.asset.value),
    )
    return current, upcoming
