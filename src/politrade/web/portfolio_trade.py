"""Execute Polymarket buy/sell from the dashboard."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from politrade.api.clob_client import ClobClientWrapper
from politrade.api.data_client import DataClient
from politrade.config import AppConfig
from politrade.execution.clob_errors import classify_clob_error, format_risk_reason
from politrade.execution.risk import RiskManager
from politrade.logging_setup import get_logger
from politrade.storage.repository import Repository

log = get_logger(__name__)


@dataclass
class TradeResult:
    ok: bool
    message: str
    reason: str = ""
    response: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "message": self.message,
            "reason": self.reason,
        }


def normalize_market_slug(raw: str) -> str:
    s = (raw or "").strip().rstrip("/")
    if not s:
        return ""
    if "polymarket.com" in s:
        path = urlparse(s).path.strip("/")
        if not path:
            return s
        parts = [p for p in path.split("/") if p]
        if parts and parts[0] in ("event", "market", "sports"):
            return parts[-1]
        return parts[-1]
    if "/" in s:
        return s.rsplit("/", 1)[-1]
    return s


def _parse_json_list(raw: Any) -> list[Any]:
    if raw is None:
        return []
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            return []
    if isinstance(raw, list):
        return raw
    return []


def market_outcomes(market: dict[str, Any]) -> list[dict[str, str]]:
    ids = _parse_json_list(market.get("clobTokenIds"))
    names = _parse_json_list(market.get("outcomes"))
    if not ids:
        return []
    out: list[dict[str, str]] = []
    for i, tid in enumerate(ids):
        label = str(names[i]) if i < len(names) else f"Outcome {i + 1}"
        out.append({"outcome": label, "token_id": str(tid)})
    return out


def fetch_market_preview(
    slug: str,
    *,
    config: AppConfig | None = None,
    clob: ClobClientWrapper | None = None,
) -> dict[str, Any]:
    slug = normalize_market_slug(slug)
    if not slug:
        raise ValueError("חסר slug או URL של שוק")

    data = DataClient(config)
    own_clob = clob is None
    clob = clob or ClobClientWrapper(config)
    try:
        market = data.get_market_by_slug(slug)
        if not market:
            raise ValueError(f"שוק לא נמצא: {slug}")

        outcomes = market_outcomes(market)
        if not outcomes:
            raise ValueError("לא נמצאו token IDs לשוק הזה")

        enriched: list[dict[str, Any]] = []
        for row in outcomes:
            mid = clob.get_mid_price(row["token_id"]) if clob.is_configured else None
            enriched.append({**row, "mid_price": mid, "mid_cents": round(mid * 100, 1) if mid else None})

        return {
            "slug": slug,
            "title": str(market.get("question") or market.get("title") or slug),
            "condition_id": str(market.get("conditionId") or ""),
            "closed": bool(market.get("closed")),
            "active": market.get("active", True) is not False,
            "outcomes": enriched,
        }
    finally:
        data.close()


def _position_size(data: DataClient, funder: str, token_id: str) -> float | None:
    positions = data.get_positions(funder, limit=200)
    for raw in positions:
        asset = str(raw.get("asset") or raw.get("asset_id") or "")
        if asset == token_id:
            return float(raw.get("size") or 0)
    return None


def _check_buy_risk(risk: RiskManager, amount_usd: float) -> TradeResult | None:
    if risk.is_kill_switch_active():
        return TradeResult(False, format_risk_reason("kill_switch_active"), "kill_switch_active")
    max_pos = float(risk.config.risk.get("max_position_usd", 50))
    if amount_usd < 1.0:
        return TradeResult(False, "סכום מינימלי: $1", "position_too_small")
    if amount_usd > max_pos:
        return TradeResult(
            False,
            f"מקסימום לעסקה: ${max_pos:.0f}",
            "position_too_small",
        )
    balance = risk.clob.get_balance() if risk.clob.is_configured else None
    if balance is not None and balance < amount_usd:
        return TradeResult(False, format_risk_reason("insufficient_balance"), "insufficient_balance")
    return None


def execute_portfolio_buy(
    token_id: str,
    amount_usd: float,
    *,
    title: str = "",
    config: AppConfig | None = None,
    repo: Repository | None = None,
) -> TradeResult:
    from politrade.config import AppConfig as _AppConfig

    cfg = config or _AppConfig()
    repo = repo or Repository(cfg)
    clob = ClobClientWrapper(cfg)
    risk = RiskManager(cfg, repo, clob)

    if not clob.is_configured:
        return TradeResult(False, "ארנק לא מוגדר — הגדר Private Key + Funder", "wallet_not_configured")

    token_id = token_id.strip()
    if not re.fullmatch(r"\d+", token_id):
        return TradeResult(False, "token_id לא תקין", "invalid_token")

    blocked = _check_buy_risk(risk, amount_usd)
    if blocked:
        return blocked

    if not clob.has_buy_liquidity(token_id):
        return TradeResult(False, "אין נזילות לקנייה בשוק", "no_liquidity")

    try:
        resp = clob.market_buy(token_id, amount_usd)
        msg = f"קנייה בוצעה: ${amount_usd:.2f}" + (f" · {title[:60]}" if title else "")
        repo.audit("info", "portfolio_buy", f"{token_id} ${amount_usd:.2f} {title[:80]}")
        log.info("portfolio_buy_ok", token_id=token_id, amount=amount_usd)
        return TradeResult(True, msg, response=resp if isinstance(resp, dict) else None)
    except Exception as exc:
        reason, msg = classify_clob_error(exc)
        repo.audit("error", "portfolio_buy_failed", f"{reason}: {exc}")
        log.error("portfolio_buy_failed", error=str(exc))
        return TradeResult(False, msg, reason)


def execute_portfolio_sell(
    token_id: str,
    shares: float | None = None,
    *,
    title: str = "",
    config: AppConfig | None = None,
    repo: Repository | None = None,
) -> TradeResult:
    from politrade.config import AppConfig as _AppConfig

    cfg = config or _AppConfig()
    repo = repo or Repository(cfg)
    clob = ClobClientWrapper(cfg)
    risk = RiskManager(cfg, repo, clob)

    if not clob.is_configured:
        return TradeResult(False, "ארנק לא מוגדר — הגדר Private Key + Funder", "wallet_not_configured")

    if risk.is_kill_switch_active():
        return TradeResult(False, format_risk_reason("kill_switch_active"), "kill_switch_active")

    token_id = token_id.strip()
    funder = cfg.funder_address
    if not funder:
        return TradeResult(False, "חסר Funder Address", "wallet_not_configured")

    data = DataClient(cfg)
    try:
        held = _position_size(data, funder, token_id)
        if held is None or held < 0.01:
            return TradeResult(False, "אין פוזיציה פתוחה ב-token הזה", "no_position")

        sell_size = held if shares is None or shares <= 0 else min(float(shares), held)
        if sell_size < 0.01:
            return TradeResult(False, "כמות מניות קטנה מדי", "position_too_small")

        clob.cancel_orders_for_token(token_id)
        resp = clob.market_sell(token_id, sell_size)
        msg = f"מכירה בוצעה: {sell_size:.2f} shares" + (f" · {title[:60]}" if title else "")
        repo.audit("info", "portfolio_sell", f"{token_id} {sell_size:.2f} {title[:80]}")
        log.info("portfolio_sell_ok", token_id=token_id, shares=sell_size)
        return TradeResult(True, msg, response=resp if isinstance(resp, dict) else None)
    except Exception as exc:
        reason, msg = classify_clob_error(exc)
        repo.audit("error", "portfolio_sell_failed", f"{reason}: {exc}")
        log.error("portfolio_sell_failed", error=str(exc))
        return TradeResult(False, msg, reason)
    finally:
        data.close()
