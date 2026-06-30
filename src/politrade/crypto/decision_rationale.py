"""Structured Hebrew rationale for every sim/live decision."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

from politrade.crypto.strategy import DecisionAction, StrategyDecision


class FactorCategory(str, Enum):
    TIME = "time"
    PROFIT = "profit"
    RISK = "risk"
    LIQUIDITY = "liquidity"
    MODE = "mode"
    BALANCE = "balance"
    STATE = "state"


CATEGORY_HE: dict[str, str] = {
    FactorCategory.TIME.value: "זמן",
    FactorCategory.PROFIT.value: "רווח",
    FactorCategory.RISK.value: "סיכון",
    FactorCategory.LIQUIDITY.value: "נזילות",
    FactorCategory.MODE.value: "אסטרטגיה",
    FactorCategory.BALANCE.value: "יתרה",
    FactorCategory.STATE.value: "מצב",
}

STATUS_HE: dict[str, str] = {
    "pass": "עבר",
    "fail": "חוסם",
    "warn": "אזהרה",
    "info": "מידע",
}


@dataclass
class DecisionFactor:
    category: str
    status: str
    label_he: str
    detail_he: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "category_he": CATEGORY_HE.get(self.category, self.category),
            "status": self.status,
            "status_he": STATUS_HE.get(self.status, self.status),
            "label_he": self.label_he,
            "detail_he": self.detail_he,
        }


@dataclass
class DecisionContext:
    seconds_elapsed: int = 0
    seconds_remaining: int = 0
    phase: str = ""
    factors: list[DecisionFactor] = field(default_factory=list)
    blocker_category: str | None = None

    def add(self, factor: DecisionFactor) -> None:
        self.factors.append(factor)
        if factor.status == "fail" and self.blocker_category is None:
            self.blocker_category = factor.category

    def time_info(
        self,
        *,
        elapsed: int,
        remaining: int,
        phase: str,
        first_sec: int,
        last_sec: int,
    ) -> None:
        self.seconds_elapsed = elapsed
        self.seconds_remaining = remaining
        self.phase = phase
        minute = elapsed // 60 + 1
        if phase == "early":
            wait = max(0, first_sec - elapsed)
            self.add(DecisionFactor(
                FactorCategory.TIME.value, "fail", "מוקדם מדי",
                f"דקה {minute} · {elapsed}s מהתחלה · גרסה דורשת כניסה מ-{first_sec}s "
                f"(עוד {wait}s). בודקים אם כניסה מוקדמת משתלמת.",
            ))
        elif phase == "late":
            self.add(DecisionFactor(
                FactorCategory.TIME.value, "fail", "מאוחר מדי",
                f"דקה {minute} · נשארו {remaining}s · גרסה יוצאת {last_sec}s לפני הסוף — "
                f"רווח פוטנציאלי נמוך, סיכון גבוה.",
            ))
        elif phase == "bet":
            bucket = "דקה ראשונה" if elapsed < 60 else ("דקה 2" if elapsed < 120 else "דקה 3+")
            self.add(DecisionFactor(
                FactorCategory.TIME.value, "pass", "חלון כניסה פתוח",
                f"{bucket} · {elapsed}s elapsed · {remaining}s נותרו לסגירה.",
            ))

    def profit_info(
        self,
        *,
        edge: float | None,
        min_edge: float,
        ask: float | None,
        max_entry: float,
        bet_usd: float,
    ) -> None:
        if ask is None:
            self.add(DecisionFactor(
                FactorCategory.PROFIT.value, "warn", "אין מחיר",
                "לא ניתן לחשב רווח צפוי ללא מחיר CLOB.",
            ))
            return
        edge_val = edge if edge is not None else 0.0
        payout = (bet_usd / ask) - bet_usd if ask > 0 else 0
        if min_edge > 0 and edge_val < min_edge:
            self.add(DecisionFactor(
                FactorCategory.PROFIT.value, "fail", "edge נמוך",
                f"edge {edge_val:.1f}% < מינימום {min_edge}% · מחיר {ask:.3f} · "
                f"רווח צפוי ~${payout:.2f} על ${bet_usd:.0f}.",
            ))
        elif ask > max_entry:
            self.add(DecisionFactor(
                FactorCategory.PROFIT.value, "fail", "מחיר כניסה גבוה",
                f"מחיר {ask:.3f} > מקס {max_entry:.2f} · edge {edge_val:.1f}% · "
                f"רווח קטן מדי ביחס לסיכון.",
            ))
        else:
            self.add(DecisionFactor(
                FactorCategory.PROFIT.value, "pass", "רווח מספיק",
                f"edge {edge_val:.1f}% · מחיר {ask:.3f} · רווח צפוי ~${payout:.2f} על ${bet_usd:.0f}.",
            ))

    def risk_info(
        self,
        *,
        delta: float | None,
        min_move: float,
        side: str | None,
        mode: str,
        confidence: float,
    ) -> None:
        d = abs(delta or 0)
        if min_move > 0 and delta is not None and d < min_move:
            self.add(DecisionFactor(
                FactorCategory.RISK.value, "fail", "תזוזה קטנה",
                f"Chainlink Δ{d:.3f}% < מינימום {min_move}% — כיוון לא מספיק ברור.",
            ))
        else:
            vol_label = "נמוכה" if d < 0.03 else ("בינונית" if d < 0.08 else "גבוהה")
            self.add(DecisionFactor(
                FactorCategory.RISK.value, "pass" if d >= min_move or min_move == 0 else "warn",
                f"תנודתיות {vol_label}",
                f"Δ{d:.3f}% · כיוון {side or '?'} · מצב {mode} · ביטחון {confidence:.0f}/100.",
            ))

    def mode_info(self, mode: str, side: str | None) -> None:
        labels = {
            "follow_oracle": "עוקב אחרי Chainlink",
            "contrarian": "נגד Chainlink",
            "best_edge": "בוחר edge גבוה יותר",
            "always_up": "תמיד UP",
            "always_down": "תמיד DOWN",
        }
        self.add(DecisionFactor(
            FactorCategory.MODE.value, "info", labels.get(mode, mode),
            f"גרסה בוחרת {side or '—'} לפי מצב {mode}.",
        ))


def format_rationale(
    decision: StrategyDecision,
    ctx: DecisionContext,
    *,
    executed: bool | None = None,
    execution_note: str = "",
) -> str:
    """Multi-line Hebrew explanation for UI."""
    action = decision.action.value
    if action == "bet":
        headline = "✓ בוצעה עסקה" if executed is not False else "→ מומלץ להמר (טרם בוצע)"
    elif action == "wait":
        headline = "⏳ ממתין — לא בוצע"
    else:
        headline = "✗ לא בוצע"

    if executed is False and execution_note:
        headline = "✗ לא בוצע"

    lines = [headline]
    if execution_note:
        lines.append(f"  סיבת אי-ביצוע: {execution_note}")

    blocker = ctx.blocker_category or decision.blocker_category
    if blocker and action != "bet":
        lines.append(f"  חוסם עיקרי: {CATEGORY_HE.get(blocker, blocker)}")

    for f in ctx.factors or decision.factors:
        fd = f if isinstance(f, DecisionFactor) else DecisionFactor(**f) if isinstance(f, dict) else None
        if fd is None:
            continue
        cat = CATEGORY_HE.get(fd.category, fd.category)
        st = STATUS_HE.get(fd.status, fd.status)
        lines.append(f"  [{cat}/{st}] {fd.label_he}: {fd.detail_he}")

    if decision.reason and action == "bet":
        lines.append(f"  סיכום: {decision.reason}")

    return "\n".join(lines)


def attach_rationale(
    decision: StrategyDecision,
    ctx: DecisionContext,
    *,
    executed: bool | None = None,
    execution_note: str = "",
) -> StrategyDecision:
    decision.factors = list(ctx.factors)
    decision.blocker_category = ctx.blocker_category
    decision.seconds_elapsed = ctx.seconds_elapsed
    decision.rationale_he = format_rationale(
        decision, ctx, executed=executed, execution_note=execution_note,
    )
    return decision


def factors_to_json(factors: list[Any]) -> str:
    import json

    out = []
    for f in factors:
        if hasattr(f, "to_dict"):
            out.append(f.to_dict())
        elif isinstance(f, dict):
            out.append(f)
    return json.dumps(out, ensure_ascii=False)


def aggregate_variant_stats(decisions: list[dict[str, Any]]) -> dict[str, Any]:
    by_action = {"bet": 0, "wait": 0, "skip": 0}
    by_blocker: dict[str, int] = {}
    executed = 0
    not_executed = 0

    for d in decisions:
        action = d.get("action", "wait")
        by_action[action] = by_action.get(action, 0) + 1
        if d.get("executed"):
            executed += 1
        elif d.get("executed") is False:
            not_executed += 1
        blocker = d.get("blocker_category")
        if blocker and action != "bet":
            by_blocker[blocker] = by_blocker.get(blocker, 0) + 1

    return {
        "by_action": by_action,
        "by_blocker": by_blocker,
        "executed": executed,
        "not_executed": not_executed,
        "total": len(decisions),
    }
