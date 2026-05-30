"""Cache leader trade opportunities to avoid API rate limits."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from politrade.storage.repository import Repository

CACHE_PREFIX = "opp_cache:"


def _key(address: str) -> str:
    return f"{CACHE_PREFIX}{address.lower()}"


def get_cached(
    address: str,
    *,
    repo: Repository | None = None,
    ttl_minutes: int = 20,
) -> dict[str, Any] | list[dict] | None:
    r = repo or Repository()
    raw = r.get_state(_key(address))
    if not raw:
        return None
    try:
        payload = json.loads(raw)
        fetched = datetime.fromisoformat(payload["fetched_at"])
        if fetched.tzinfo is None:
            fetched = fetched.replace(tzinfo=timezone.utc)
        age_min = (datetime.now(timezone.utc) - fetched).total_seconds() / 60
        if age_min > ttl_minutes:
            return None
        items = payload.get("items")
        if isinstance(items, dict):
            return items
        if isinstance(items, list):
            return items
        return None
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None


def set_cached(
    address: str,
    items: dict[str, Any] | list[dict],
    *,
    repo: Repository | None = None,
) -> None:
    r = repo or Repository()
    payload = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "items": items,
    }
    r.set_state(_key(address), json.dumps(payload))
