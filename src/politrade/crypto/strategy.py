"""Betting strategy for 5-minute crypto windows."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from politrade.config import AppConfig
from politrade.crypto.price_feed import OracleSnapshot, TokenPrices, edge_pct_from_ask
from politrade.crypto.window import BetSide, CryptoWindow, WindowPhase


class DecisionAction(str, Enum):
    BET = "bet"
    SKIP = "skip"
    WAIT = "wait"


@dataclass
class StrategyDecision:
    action: DecisionAction
    side: BetSide | None = None
    token_id: str = ""
    entry_ask: float | None = None
    edge_pct: float | None = None
    reason: str = ""
    confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action.value,
            "side": self.side.value if self.side else None,
            "token_id": self.token_id,
            "entry_ask": self.entry_ask,
            "edge_pct": round(self.edge_pct, 2) if self.edge_pct is not None else None,
            "reason": self.reason,
            "confidence": round(self.confidence, 2),
        }


def crypto_cfg(config: AppConfig) -> dict[str, Any]:
    if hasattr(config, "crypto"):
        base = dict(config.crypto)
    else:
        base = dict(config.get("crypto", default={}))
    user = getattr(config, "user_settings", None) or {}
    for key in (
        "bet_usd", "min_edge_pct", "max_entry_price", "min_move_pct",
        "no_bet_first_seconds", "no_bet_last_seconds", "auto_bet",
    ):
        if key in user:
            base[key] = user[key]
    return base


def evaluate_window(
    window: CryptoWindow,
    oracle: OracleSnapshot,
    tokens: TokenPrices,
    config: AppConfig,
    *,
    already_bet: bool = False,
    has_liquidity_fn: Any = None,
    now: float | None = None,
) -> StrategyDecision:
    cfg = crypto_cfg(config)
    phase = window.phase(now)

    if already_bet:
        return StrategyDecision(action=DecisionAction.SKIP, reason="כבר הימרנו בחלון זה")

    if phase == WindowPhase.CLOSED:
        return StrategyDecision(action=DecisionAction.SKIP, reason="חלון נסגר")

    if phase == WindowPhase.EARLY:
        return StrategyDecision(
            action=DecisionAction.WAIT,
            reason=f"מוקדם מדי — המתן לדקה 3 ({cfg.get('no_bet_first_seconds', 120)}s)",
        )

    if phase == WindowPhase.LATE:
        return StrategyDecision(
            action=DecisionAction.SKIP,
            reason="מאוחר מדי — דקה אחרונה, רווח נמוך",
        )

    delta = oracle.delta_pct
    if delta is None or oracle.open_price is None:
        return StrategyDecision(action=DecisionAction.WAIT, reason="ממתין למחיר Chainlink")

    min_move = float(cfg.get("min_move_pct", 0.04))
    if abs(delta) < min_move:
        return StrategyDecision(
            action=DecisionAction.WAIT,
            reason=f"תזוזה קטנה מדי ({delta:.3f}% < {min_move}%)",
        )

    side = BetSide.UP if delta > 0 else BetSide.DOWN
    if side == BetSide.UP:
        ask = tokens.up_ask or tokens.up_mid
        token_id = window.up_token_id
    else:
        ask = tokens.down_ask or tokens.down_mid
        token_id = window.down_token_id

    if ask is None:
        return StrategyDecision(action=DecisionAction.WAIT, reason="אין מחיר CLOB")

    max_entry = float(cfg.get("max_entry_price", 0.87))
    if ask > max_entry:
        edge = edge_pct_from_ask(ask)
        return StrategyDecision(
            action=DecisionAction.SKIP,
            side=side,
            token_id=token_id,
            entry_ask=ask,
            edge_pct=edge,
            reason=f"רווח נמוך — מחיר {ask:.3f} > {max_entry}",
        )

    edge = edge_pct_from_ask(ask)
    min_edge = float(cfg.get("min_edge_pct", 15))
    if edge is None or edge < min_edge:
        return StrategyDecision(
            action=DecisionAction.SKIP,
            side=side,
            token_id=token_id,
            entry_ask=ask,
            edge_pct=edge,
            reason=f"edge {edge:.1f}% < {min_edge}% נדרש",
        )

    if has_liquidity_fn and not has_liquidity_fn(token_id):
        return StrategyDecision(
            action=DecisionAction.SKIP,
            side=side,
            token_id=token_id,
            entry_ask=ask,
            edge_pct=edge,
            reason="אין נזילות לקנייה",
        )

    confidence = min(100.0, abs(delta) / min_move * 30 + (edge or 0))

    return StrategyDecision(
        action=DecisionAction.BET,
        side=side,
        token_id=token_id,
        entry_ask=ask,
        edge_pct=edge,
        reason=f"{'עלייה' if side == BetSide.UP else 'ירידה'} {abs(delta):.3f}%, edge {edge:.1f}%",
        confidence=confidence,
    )
