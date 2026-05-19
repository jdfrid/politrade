"""Global throttle for Polymarket Data API requests."""

from __future__ import annotations

import threading
import time

_lock = threading.Lock()
_last_request_at = 0.0
_min_interval = 1.25


def configure_min_interval(seconds: float) -> None:
    global _min_interval
    _min_interval = max(0.5, seconds)


def throttle() -> None:
    global _last_request_at
    with _lock:
        now = time.monotonic()
        wait = _min_interval - (now - _last_request_at)
        if wait > 0:
            time.sleep(wait)
        _last_request_at = time.monotonic()
