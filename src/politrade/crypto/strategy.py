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
    factors: list[Any] = None  # DecisionFactor | dict
    blocker_category: str | None = None
    rationale_he: str = ""
    seconds_elapsed: int = 0

    def __post_init__(self) -> None:
        if self.factors is None:
            self.factors = []

    def to_dict(self) -> dict[str, Any]:
        from politrade.crypto.decision_rationale import factors_to_json

        return {
            "action": self.action.value,
            "side": self.side.value if self.side else None,
            "token_id": self.token_id,
            "entry_ask": self.entry_ask,
            "edge_pct": round(self.edge_pct, 2) if self.edge_pct is not None else None,
            "reason": self.reason,
            "confidence": round(self.confidence, 2),
            "blocker_category": self.blocker_category,
            "rationale_he": self.rationale_he,
            "seconds_elapsed": self.seconds_elapsed,
            "factors": __import__("json").loads(factors_to_json(self.factors)) if self.factors else [],
        }


def crypto_cfg(config: AppConfig, cfg_override: dict[str, Any] | None = None) -> dict[str, Any]:
    if hasattr(config, "crypto"):
        base = dict(config.crypto)
    else:
        base = dict(config.get("crypto", default={}))
    user = getattr(config, "user_settings", None) or {}
    for key in (
        "bet_usd", "min_edge_pct", "max_entry_price", "min_move_pct",
        "no_bet_first_seconds", "no_bet_last_seconds", "auto_bet", "strategy_mode",
        "max_wallet_usd",
    ):
        if key in user:
            base[key] = user[key]
    if cfg_override:
        base.update(cfg_override)
    return base


def crypto_cfg_with_experience(
    config: AppConfig,
    repo: Repository | None = None,
    cfg_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from politrade.crypto.experience import load_experience
    from politrade.storage.repository import Repository as Repo

    cfg = crypto_cfg(config, cfg_override)
    r = repo or Repo(config)
    try:
        cfg["_experience"] = load_experience(r)
    except Exception:
        cfg["_experience"] = None
    return cfg


def _phase_with_cfg(window: CryptoWindow, cfg: dict[str, Any], now: float | None = None) -> WindowPhase:
    import time as _time

    ts = now if now is not None else _time.time()
    if ts >= window.window_end_ts:
        return WindowPhase.CLOSED
    elapsed = int(ts) - window.window_ts
    first = int(cfg.get("no_bet_first_seconds", 0))
    last = int(cfg.get("no_bet_last_seconds", 0))
    from politrade.crypto.window import WINDOW_SECONDS

    if elapsed < first:
        return WindowPhase.EARLY
    if elapsed >= WINDOW_SECONDS - last:
        return WindowPhase.LATE
    return WindowPhase.BET


def _pick_side(
    mode: str,
    delta: float | None,
    up_ask: float | None,
    down_ask: float | None,
) -> BetSide | None:
    if mode == "always_up":
        return BetSide.UP
    if mode == "always_down":
        return BetSide.DOWN
    if mode == "best_edge":
        up_e = edge_pct_from_ask(up_ask) if up_ask else None
        down_e = edge_pct_from_ask(down_ask) if down_ask else None
        if up_e is None and down_e is None:
            return None
        if down_e is None or (up_e is not None and up_e >= (down_e or 0)):
            return BetSide.UP
        return BetSide.DOWN
    if delta is None:
        return None
    if mode == "contrarian":
        return BetSide.DOWN if delta > 0 else BetSide.UP
    return BetSide.UP if delta > 0 else BetSide.DOWN


def evaluate_window(
    window: CryptoWindow,
    oracle: OracleSnapshot,
    tokens: TokenPrices,
    config: AppConfig,
    *,
    already_bet: bool = False,
    has_liquidity_fn: Any = None,
    now: float | None = None,
    cfg_override: dict[str, Any] | None = None,
) -> StrategyDecision:
    from politrade.crypto.decision_rationale import (
        DecisionContext,
        DecisionFactor,
        FactorCategory,
        attach_rationale,
    )
    from politrade.crypto.window import WINDOW_SECONDS

    cfg = crypto_cfg(config, cfg_override)
    phase = _phase_with_cfg(window, cfg, now)
    elapsed = window.seconds_elapsed(now)
    remaining = max(0, WINDOW_SECONDS - elapsed)
    first = int(cfg.get("no_bet_first_seconds", 0))
    last = int(cfg.get("no_bet_last_seconds", 0))
    bet_usd = float(cfg.get("bet_usd", 5))
    mode = str(cfg.get("strategy_mode", "follow_oracle"))
    ctx = DecisionContext()

    def finish(decision: StrategyDecision, **kw) -> StrategyDecision:
        return attach_rationale(decision, ctx, **kw)

    if already_bet:
        ctx.add(DecisionFactor(FactorCategory.STATE.value, "info", "כבר הימרנו", "עסקה אחת לחלון."))
        return finish(StrategyDecision(action=DecisionAction.SKIP, reason="כבר הימרנו בחלון זה"))

    if phase == WindowPhase.CLOSED:
        ctx.add(DecisionFactor(FactorCategory.STATE.value, "fail", "חלון נסגר", "אין מסחר."))
        return finish(StrategyDecision(action=DecisionAction.SKIP, reason="חלון נסגר"))

    ctx.time_info(
        elapsed=elapsed, remaining=remaining, phase=phase.value,
        first_sec=first, last_sec=last,
    )

    if phase == WindowPhase.EARLY:
        return finish(StrategyDecision(
            action=DecisionAction.WAIT,
            reason=f"מוקדם — כניסה מ-{first}s",
            seconds_elapsed=elapsed,
        ))

    if phase == WindowPhase.LATE:
        return finish(StrategyDecision(
            action=DecisionAction.SKIP,
            reason=f"מאוחר — יציאה לפני {last}s מהסוף",
            seconds_elapsed=elapsed,
        ))

    delta = oracle.delta_pct
    up_ask = tokens.up_ask or tokens.up_mid
    down_ask = tokens.down_ask or tokens.down_mid

    if mode not in ("always_up", "always_down") and delta is None and oracle.open_price is None:
        ctx.add(DecisionFactor(
            FactorCategory.STATE.value, "warn", "אין Oracle",
            "ממתינים למחיר Chainlink לפתיחת החלון.",
        ))
        return finish(StrategyDecision(action=DecisionAction.WAIT, reason="ממתין למחיר Chainlink", seconds_elapsed=elapsed))

    min_move = float(cfg.get("min_move_pct", 0))
    if min_move > 0 and delta is not None and abs(delta) < min_move and mode not in ("always_up", "always_down", "best_edge"):
        ctx.risk_info(delta=delta, min_move=min_move, side=None, mode=mode, confidence=0)
        return finish(StrategyDecision(
            action=DecisionAction.WAIT,
            reason=f"תזוזה {abs(delta):.3f}% < {min_move}%",
            seconds_elapsed=elapsed,
        ))

    side = _pick_side(mode, delta, up_ask, down_ask)
    ctx.mode_info(mode, side.value if side else None)

    if side is None:
        ctx.add(DecisionFactor(FactorCategory.MODE.value, "fail", "אין כיוון", f"מצב {mode} לא מצא צד."))
        return finish(StrategyDecision(action=DecisionAction.WAIT, reason="אין כיוון", seconds_elapsed=elapsed))

    if side == BetSide.UP:
        ask = up_ask
        token_id = window.up_token_id
    else:
        ask = down_ask
        token_id = window.down_token_id

    if ask is None:
        ctx.add(DecisionFactor(FactorCategory.LIQUIDITY.value, "fail", "אין מחיר", "CLOB לא החזיר ask."))
        return finish(StrategyDecision(action=DecisionAction.WAIT, reason="אין מחיר CLOB", seconds_elapsed=elapsed))

    max_entry = float(cfg.get("max_entry_price", 0.99))
    edge = edge_pct_from_ask(ask)
    min_edge = float(cfg.get("min_edge_pct", 0))
    ctx.profit_info(edge=edge, min_edge=min_edge, ask=ask, max_entry=max_entry, bet_usd=bet_usd)

    if ask > max_entry:
        ctx.risk_info(delta=delta, min_move=min_move, side=side.value, mode=mode, confidence=0)
        return finish(StrategyDecision(
            action=DecisionAction.SKIP,
            side=side,
            token_id=token_id,
            entry_ask=ask,
            edge_pct=edge,
            reason=f"מחיר {ask:.3f} > {max_entry}",
            seconds_elapsed=elapsed,
        ))

    if min_edge > 0 and (edge is None or edge < min_edge):
        ctx.risk_info(delta=delta, min_move=min_move, side=side.value, mode=mode, confidence=0)
        return finish(StrategyDecision(
            action=DecisionAction.SKIP,
            side=side,
            token_id=token_id,
            entry_ask=ask,
            edge_pct=edge,
            reason=f"edge {edge:.1f}% < {min_edge}%",
            seconds_elapsed=elapsed,
        ))

    if has_liquidity_fn and token_id and not has_liquidity_fn(token_id):
        ctx.add(DecisionFactor(
            FactorCategory.LIQUIDITY.value, "fail", "אין נזילות",
            "אין מספיק נפח קנייה ב-CLOB.",
        ))
        ctx.risk_info(delta=delta, min_move=min_move, side=side.value, mode=mode, confidence=0)
        return finish(StrategyDecision(
            action=DecisionAction.SKIP,
            side=side,
            token_id=token_id,
            entry_ask=ask,
            edge_pct=edge,
            reason="אין נזילות לקנייה",
            seconds_elapsed=elapsed,
        ))

    move_denom = min_move if min_move > 0 else 0.01
    confidence = min(100.0, (abs(delta or 0) / move_denom) * 20 + (edge or 0))
    ctx.risk_info(delta=delta, min_move=min_move, side=side.value, mode=mode, confidence=confidence)

    dir_label = mode if mode not in ("follow_oracle",) else ("עלייה" if side == BetSide.UP else "ירידה")
    bet_decision = finish(StrategyDecision(
        action=DecisionAction.BET,
        side=side,
        token_id=token_id,
        entry_ask=ask,
        edge_pct=edge,
        reason=f"{dir_label} · Δ{abs(delta or 0):.3f}% · edge {edge:.1f}% · {mode}",
        confidence=confidence,
        seconds_elapsed=elapsed,
    ))

    experience = cfg.get("_experience")
    if experience:
        from politrade.crypto.experience import apply_experience_to_decision

        bet_decision = apply_experience_to_decision(
            bet_decision,
            window,
            base_min_edge=min_edge,
            experience=experience,
        )
        if bet_decision.action != DecisionAction.BET:
            return bet_decision

    return bet_decision
