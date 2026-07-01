"""Display helpers for simulation bets and transactions."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from politrade.crypto.window import WINDOW_SECONDS


def format_window_period_he(window_ts: int) -> str:
    start = datetime.fromtimestamp(window_ts, tz=timezone.utc)
    end = start + timedelta(seconds=WINDOW_SECONDS)
    return f"{start.strftime('%d/%m/%Y %H:%M')} – {end.strftime('%H:%M')} UTC"


def format_placed_at_he(dt: datetime | None) -> str:
    if dt is None:
        return "—"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%d/%m/%Y %H:%M:%S UTC")


def bet_status_display(status: str) -> dict[str, str]:
    s = (status or "open").lower()
    if s == "won":
        return {"status_label_he": "הצלחה", "status_class": "ok"}
    if s == "lost":
        return {"status_label_he": "כשלון", "status_class": "err"}
    if s == "open":
        return {"status_label_he": "פתוח — ממתין לתוצאה", "status_class": "warn"}
    return {"status_label_he": s, "status_class": "muted"}


def fallback_market_title(asset: str, slug: str, window_ts: int) -> str:
    period = format_window_period_he(window_ts)
    return f"{asset.upper()} Up or Down · 5m · {period}"


def resolve_market_title(
    *,
    market_title: str | None,
    asset: str,
    slug: str,
    window_ts: int,
) -> str:
    if market_title and market_title.strip():
        return market_title.strip()
    return fallback_market_title(asset, slug, window_ts)


def enrich_sim_bet_dict(bet: Any) -> dict[str, Any]:
    import json as _json

    from politrade.crypto.sim_engine import sim_bet_to_dict

    base = sim_bet_to_dict(bet)
    title = resolve_market_title(
        market_title=getattr(bet, "market_title", None),
        asset=bet.asset,
        slug=bet.slug,
        window_ts=bet.window_ts,
    )
    st = bet_status_display(bet.status)
    base.update({
        "market_title": title,
        "window_period_he": format_window_period_he(bet.window_ts),
        "placed_at_he": format_placed_at_he(getattr(bet, "created_at", None)),
        "status_label_he": st["status_label_he"],
        "status_class": st["status_class"],
    })
    return base


def enrich_variant_bet_dict(bet: Any, *, variant_label: str = "") -> dict[str, Any]:
    import json as _json

    factors = []
    raw = getattr(bet, "factors_json", None)
    if raw:
        try:
            factors = _json.loads(raw)
        except _json.JSONDecodeError:
            pass

    title = resolve_market_title(
        market_title=getattr(bet, "market_title", None),
        asset=bet.asset,
        slug=bet.slug,
        window_ts=bet.window_ts,
    )
    st = bet_status_display(bet.status)
    return {
        "id": bet.id,
        "variant_id": bet.variant_id,
        "variant_label": variant_label,
        "asset": bet.asset.upper(),
        "slug": bet.slug,
        "market_title": title,
        "window_period_he": format_window_period_he(bet.window_ts),
        "placed_at_he": format_placed_at_he(getattr(bet, "created_at", None)),
        "side": bet.side,
        "bet_usd": bet.bet_usd,
        "status": bet.status,
        "status_label_he": st["status_label_he"],
        "status_class": st["status_class"],
        "realized_pnl": bet.realized_pnl,
        "rationale_he": bet.rationale_he,
        "decision_reason": bet.decision_reason,
        "seconds_at_entry": bet.seconds_at_entry,
        "factors": factors,
        "created_at": bet.created_at.isoformat() if bet.created_at else "",
    }
