"""Strategy parameter space for parallel simulation exploration."""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import asdict, dataclass
from typing import Any, Iterator

STRATEGY_MODES = (
    "follow_oracle",
    "contrarian",
    "best_edge",
    "always_up",
    "always_down",
)

FIRST_SECONDS_OPTIONS = (0, 5, 10, 15, 20, 30, 45, 60, 75, 90, 105, 120, 150, 180, 210, 240)
LAST_SECONDS_OPTIONS = (0, 10, 15, 30, 45, 60, 90, 120, 150, 180)
EDGE_OPTIONS = (0, 2, 3, 5, 8, 10, 12, 15, 18, 22, 28, 35, 45)
MOVE_OPTIONS = (0, 0.005, 0.01, 0.02, 0.03, 0.05, 0.08, 0.12, 0.18, 0.25)
ENTRY_OPTIONS = (0.52, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.88, 0.92, 0.96, 0.99)
BET_USD_OPTIONS = (2, 3, 5, 8, 10, 15, 20, 25)

MAX_ACTIVE_VARIANTS = 36
INITIAL_VARIANT_COUNT = 36


@dataclass
class StrategyParams:
    strategy_mode: str = "follow_oracle"
    no_bet_first_seconds: int = 0
    no_bet_last_seconds: int = 0
    min_edge_pct: float = 0
    min_move_pct: float = 0
    max_entry_price: float = 0.99
    bet_usd: float = 5

    def to_cfg(self) -> dict[str, Any]:
        return {
            "strategy_mode": self.strategy_mode,
            "no_bet_first_seconds": self.no_bet_first_seconds,
            "no_bet_last_seconds": self.no_bet_last_seconds,
            "min_edge_pct": self.min_edge_pct,
            "min_move_pct": self.min_move_pct,
            "max_entry_price": self.max_entry_price,
            "bet_usd": self.bet_usd,
        }

    def param_hash(self) -> str:
        raw = json.dumps(self.to_cfg(), sort_keys=True)
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def label(self) -> str:
        return (
            f"{self.strategy_mode} · "
            f"t{self.no_bet_first_seconds}-{300 - self.no_bet_last_seconds}s · "
            f"edge≥{self.min_edge_pct}% · move≥{self.min_move_pct}% · "
            f"≤{self.max_entry_price:.2f} · ${self.bet_usd:.0f}"
        )


def random_params(rng: random.Random | None = None) -> StrategyParams:
    r = rng or random.Random()
    return StrategyParams(
        strategy_mode=r.choice(STRATEGY_MODES),
        no_bet_first_seconds=r.choice(FIRST_SECONDS_OPTIONS),
        no_bet_last_seconds=r.choice(LAST_SECONDS_OPTIONS),
        min_edge_pct=r.choice(EDGE_OPTIONS),
        min_move_pct=r.choice(MOVE_OPTIONS),
        max_entry_price=r.choice(ENTRY_OPTIONS),
        bet_usd=float(r.choice(BET_USD_OPTIONS)),
    )


def mutate_params(base: StrategyParams, rng: random.Random | None = None) -> StrategyParams:
    r = rng or random.Random()
    p = StrategyParams(**asdict(base))
    field_choice = r.randint(0, 6)
    if field_choice == 0:
        p.strategy_mode = r.choice(STRATEGY_MODES)
    elif field_choice == 1:
        p.no_bet_first_seconds = r.choice(FIRST_SECONDS_OPTIONS)
    elif field_choice == 2:
        p.no_bet_last_seconds = r.choice(LAST_SECONDS_OPTIONS)
    elif field_choice == 3:
        p.min_edge_pct = r.choice(EDGE_OPTIONS)
    elif field_choice == 4:
        p.min_move_pct = r.choice(MOVE_OPTIONS)
    elif field_choice == 5:
        p.max_entry_price = r.choice(ENTRY_OPTIONS)
    else:
        p.bet_usd = float(r.choice(BET_USD_OPTIONS))
    return p


def initial_population(count: int = INITIAL_VARIANT_COUNT) -> list[StrategyParams]:
    rng = random.Random(42)
    seen: set[str] = set()
    out: list[StrategyParams] = []

    # כיסוי מפורש: כניסה בדקה הראשונה (0–60s) × מצבים שונים
    for first in (0, 5, 10, 15, 20, 30, 45, 60):
        for mode in STRATEGY_MODES:
            for edge in (0, 10, 20):
                p = StrategyParams(
                    strategy_mode=mode,
                    no_bet_first_seconds=first,
                    no_bet_last_seconds=0,
                    min_edge_pct=float(edge),
                    min_move_pct=0,
                    max_entry_price=0.92,
                    bet_usd=5,
                )
                h = p.param_hash()
                if h not in seen:
                    seen.add(h)
                    out.append(p)

    for p in grid_sample(limit=30):
        h = p.param_hash()
        if h not in seen:
            seen.add(h)
            out.append(p)

    attempts = 0
    while len(out) < count and attempts < count * 30:
        attempts += 1
        p = random_params(rng)
        h = p.param_hash()
        if h in seen:
            continue
        seen.add(h)
        out.append(p)
    return out[:count]


def _parse_number_list(raw: str | None, default: tuple[float, ...]) -> list[float]:
    if not raw or not str(raw).strip():
        return [float(x) for x in default]
    out: list[float] = []
    for part in str(raw).replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.append(float(part))
        except ValueError:
            continue
    return out if out else [float(x) for x in default]


def parse_int_list(raw: str | None, default: tuple[int, ...]) -> list[int]:
    return [int(x) for x in _parse_number_list(raw, tuple(float(d) for d in default))]


def parse_float_list(raw: str | None, default: tuple[float, ...]) -> list[float]:
    return _parse_number_list(raw, default)


def parse_mode_list(raw: str | None) -> list[str]:
    if not raw or not str(raw).strip():
        return []
    modes: list[str] = []
    for part in str(raw).replace(";", ",").split(","):
        mode = part.strip()
        if mode in STRATEGY_MODES and mode not in modes:
            modes.append(mode)
    return modes


def user_scenario_grid(
    settings: dict[str, Any],
    *,
    limit: int = MAX_ACTIVE_VARIANTS,
) -> list[StrategyParams]:
    """Cartesian product of user-defined test dimensions (capped at *limit*)."""
    edges = parse_float_list(settings.get("sim_test_edges"), (0, 5, 10, 15, 20))
    bets = parse_float_list(settings.get("sim_test_bets"), (3, 5, 10, 15))
    firsts = parse_int_list(settings.get("sim_test_first_seconds"), (0, 15, 30, 60))
    lasts = parse_int_list(settings.get("sim_test_last_seconds"), (0, 30, 60))
    modes = parse_mode_list(settings.get("sim_test_modes"))
    if not modes:
        modes = [str(settings.get("crypto_strategy_mode", "follow_oracle"))]

    max_entry = float(settings.get("crypto_max_entry_price", 0.99))
    min_move = float(settings.get("crypto_min_move_pct", 0))

    combos: list[StrategyParams] = []
    seen: set[str] = set()
    for mode in modes:
        for first in firsts:
            for last in lasts:
                if first + last >= 300:
                    continue
                for edge in edges:
                    for bet in bets:
                        p = StrategyParams(
                            strategy_mode=mode,
                            no_bet_first_seconds=first,
                            no_bet_last_seconds=last,
                            min_edge_pct=edge,
                            min_move_pct=min_move,
                            max_entry_price=max_entry,
                            bet_usd=bet,
                        )
                        h = p.param_hash()
                        if h in seen:
                            continue
                        seen.add(h)
                        combos.append(p)

    if len(combos) <= limit:
        return combos

    step = len(combos) / limit
    return [combos[int(i * step)] for i in range(limit)]


def population_for_settings(
    settings: dict[str, Any],
    count: int = INITIAL_VARIANT_COUNT,
) -> list[StrategyParams]:
    if settings.get("sim_use_custom_scenarios"):
        grid = user_scenario_grid(settings, limit=count)
        if grid:
            return grid
    return initial_population(count)


def grid_sample(limit: int = 50) -> Iterator[StrategyParams]:
    """Deterministic spread across dimensions (for replay batches)."""
    n = 0
    for mode in STRATEGY_MODES:
        for first in (0, 60, 120, 180):
            for edge in (0, 10, 20):
                for move in (0, 0.03, 0.08):
                    if n >= limit:
                        return
                    yield StrategyParams(
                        strategy_mode=mode,
                        no_bet_first_seconds=first,
                        no_bet_last_seconds=0,
                        min_edge_pct=float(edge),
                        min_move_pct=move,
                        max_entry_price=0.92,
                        bet_usd=5,
                    )
                    n += 1
