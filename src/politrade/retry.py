"""HTTP retry helpers with exponential backoff."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import TypeVar

import httpx

T = TypeVar("T")

RETRYABLE_STATUS = {429, 500, 502, 503, 504}


def with_retry(
    fn: Callable[[], T],
    *,
    max_retries: int = 3,
    base_delay: float = 1.0,
    retryable: Callable[[Exception], bool] | None = None,
) -> T:
    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            return fn()
        except Exception as exc:
            last_exc = exc
            if attempt >= max_retries:
                break
            if retryable is not None and not retryable(exc):
                break
            if retryable is None and isinstance(exc, httpx.HTTPStatusError):
                if exc.response.status_code not in RETRYABLE_STATUS:
                    break
            time.sleep(base_delay * (2**attempt))
    assert last_exc is not None
    raise last_exc
