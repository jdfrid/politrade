"""Wallet budget caps for crypto 5m live and simulation."""

from __future__ import annotations

from typing import Any

from politrade.storage.repository import Repository


def wallet_cap_usd(cfg: dict[str, Any]) -> float:
    return max(0.0, float(cfg.get("max_wallet_usd", 0)))


def open_crypto_exposure(repo: Repository) -> float:
    return repo.total_open_crypto_exposure()


def open_sim_exposure(repo: Repository) -> float:
    return repo.total_open_sim_exposure()


def remaining_budget(cap: float, exposure: float) -> float:
    if cap <= 0:
        return float("inf")
    return max(0.0, cap - exposure)


def cap_bet_for_budget(
    amount: float,
    cfg: dict[str, Any],
    repo: Repository,
    *,
    live: bool = True,
) -> tuple[float, str | None]:
    """Return (capped_amount, block_reason). amount=0 when blocked."""
    cap = wallet_cap_usd(cfg)
    if cap <= 0:
        return amount, None
    exposure = open_crypto_exposure(repo) if live else open_sim_exposure(repo)
    room = remaining_budget(cap, exposure)
    if room < 1.0:
        return 0.0, f"תקרת ארנק ${cap:.0f} מלאה (${exposure:.0f} בהימורים פתוחים)"
    if amount > room:
        return round(room, 2), None
    return amount, None
