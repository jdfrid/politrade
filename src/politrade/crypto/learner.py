"""Evolution-based learning after simulation cycles."""

from __future__ import annotations

import json
from typing import Any

from politrade.config import AppConfig
from politrade.crypto.cycle_summary import update_cycle_params_after
from politrade.crypto.sim_mode import is_auto_learn_enabled
from politrade.crypto.sim_optimizer import (
    evolve_after_cycle,
    get_champion_cfg_override,
    params_to_user_settings,
    variant_params_from_row,
)
from politrade.crypto.strategy import crypto_cfg
from politrade.storage.models import SimCycle
from politrade.storage.repository import Repository
from politrade.web.user_settings import load_user_settings, save_user_settings


def run_learner_after_cycle(
    cycle: SimCycle,
    config: AppConfig | None = None,
    repo: Repository | None = None,
) -> dict[str, Any]:
    from politrade.config import AppConfig

    cfg = config or AppConfig()
    r = repo or Repository(cfg)
    params_before = _crypto_user_params(r)
    params_after = dict(params_before)

    evolution = evolve_after_cycle(cycle.window_ts, r, cfg)
    champion = r.get_champion_variant()

    from politrade.crypto.experience import refresh_experience

    experience = refresh_experience(r)

    if champion and is_auto_learn_enabled(r):
        champ_params = variant_params_from_row(champion)
        params_after = params_to_user_settings(champ_params)
        save_user_settings(r, {**load_user_settings(r), **params_after})
        update_cycle_params_after(cycle, champ_params.to_cfg(), r)

    lessons = cycle.lessons_he or ""
    if evolution.get("lesson_he"):
        lessons = (lessons + "\n" + evolution["lesson_he"]).strip()
    if experience.get("lesson_he"):
        lessons = (lessons + "\n" + experience["lesson_he"]).strip()

    if params_after != params_before or evolution.get("evolved", 0):
        r.create_sim_lesson(
            window_ts=cycle.window_ts,
            lessons_he=lessons,
            params_before=json.dumps(params_before, ensure_ascii=False),
            params_after=json.dumps(params_after, ensure_ascii=False),
        )

    return {
        "changed": params_after != params_before,
        "params_before": params_before,
        "params_after": params_after,
        "evolution": evolution,
    }


def _crypto_user_params(repo: Repository) -> dict[str, Any]:
    s = load_user_settings(repo)
    return {
        "crypto_bet_usd": s.get("crypto_bet_usd", 5),
        "crypto_min_edge_pct": s.get("crypto_min_edge_pct", 0),
        "crypto_max_entry_price": s.get("crypto_max_entry_price", 0.99),
        "crypto_min_move_pct": s.get("crypto_min_move_pct", 0),
        "crypto_no_bet_first_seconds": s.get("crypto_no_bet_first_seconds", 0),
        "crypto_no_bet_last_seconds": s.get("crypto_no_bet_last_seconds", 0),
        "crypto_strategy_mode": s.get("crypto_strategy_mode", "follow_oracle"),
    }
