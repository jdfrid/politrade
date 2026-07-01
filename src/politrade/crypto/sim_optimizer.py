"""Parallel multi-variant simulation optimizer."""

from __future__ import annotations

import json
import random
import time
from typing import Any

from politrade.config import AppConfig
from politrade.crypto.decision_rationale import aggregate_variant_stats, factors_to_json
from politrade.crypto.price_feed import get_price_feed
from politrade.crypto.strategy import DecisionAction, StrategyDecision, _phase_with_cfg, evaluate_window
from politrade.crypto.strategy_space import (
    INITIAL_VARIANT_COUNT,
    MAX_ACTIVE_VARIANTS,
    StrategyParams,
    initial_population,
    mutate_params,
    random_params,
)
from politrade.crypto.window import BetSide, CryptoWindow, WINDOW_SECONDS
from politrade.logging_setup import get_logger
from politrade.storage.models import SimVariant, SimVariantBet
from politrade.storage.repository import Repository

log = get_logger(__name__)


def variant_params_from_row(variant: SimVariant) -> StrategyParams:
    data = json.loads(variant.params_json or "{}")
    return StrategyParams(
        strategy_mode=str(data.get("strategy_mode", "follow_oracle")),
        no_bet_first_seconds=int(data.get("no_bet_first_seconds", 0)),
        no_bet_last_seconds=int(data.get("no_bet_last_seconds", 0)),
        min_edge_pct=float(data.get("min_edge_pct", 0)),
        min_move_pct=float(data.get("min_move_pct", 0)),
        max_entry_price=float(data.get("max_entry_price", 0.99)),
        bet_usd=float(data.get("bet_usd", 5)),
    )


def variant_to_dict(variant: SimVariant) -> dict[str, Any]:
    params = variant_params_from_row(variant)
    resolved = variant.wins + variant.losses
    win_rate = round(variant.wins / resolved * 100, 1) if resolved else 0.0
    return {
        "id": variant.id,
        "label": variant.label,
        "params": params.to_cfg(),
        "balance": round(variant.balance, 2),
        "start_balance": round(variant.start_balance, 2),
        "cumulative_pnl": round(variant.cumulative_pnl, 2),
        "last_cycle_pnl": round(variant.last_cycle_pnl, 2),
        "wins": variant.wins,
        "losses": variant.losses,
        "bets_total": variant.bets_total,
        "cycles_count": variant.cycles_count,
        "win_rate": win_rate,
        "rank_score": round(variant.rank_score, 2),
        "is_champion": variant.is_champion,
    }


def ensure_population(repo: Repository, start_balance: float | None = None) -> int:
    if repo.is_variants_seeded() and repo.list_active_variants():
        return len(repo.list_active_variants())

    start = start_balance or repo.get_sim_start_balance()
    existing_hashes = {v.param_hash for v in repo.list_active_variants()}
    created = 0
    for idx, params in enumerate(initial_population(INITIAL_VARIANT_COUNT)):
        h = params.param_hash()
        if h in existing_hashes:
            continue
        repo.create_sim_variant(
            label=params.label(),
            params_json=json.dumps(params.to_cfg(), ensure_ascii=False),
            param_hash=h,
            start_balance=start,
            is_champion=(idx == 0 and created == 0),
        )
        existing_hashes.add(h)
        created += 1

    if created and not repo.get_champion_variant():
        variants = repo.list_active_variants()
        if variants:
            repo.set_champion_variant(variants[0].id)

    repo.mark_variants_seeded()
    log.info("sim_variants_seeded", count=created or len(repo.list_active_variants()))
    return len(repo.list_active_variants())


def get_champion_cfg_override(repo: Repository) -> dict[str, Any] | None:
    champion = repo.get_champion_variant()
    if not champion:
        return None
    return variant_params_from_row(champion).to_cfg()


def variant_decision_to_dict(row) -> dict[str, Any]:
    import json as _json

    factors = []
    if row.factors_json:
        try:
            factors = _json.loads(row.factors_json)
        except _json.JSONDecodeError:
            factors = []
    return {
        "variant_id": row.variant_id,
        "variant_label": row.variant_label,
        "asset": row.asset.upper(),
        "slug": row.slug,
        "action": row.action,
        "side": row.side,
        "executed": row.executed,
        "execution_note": row.execution_note,
        "bet_usd": row.bet_usd,
        "entry_ask": row.entry_ask,
        "edge_pct": row.edge_pct,
        "oracle_delta_pct": row.oracle_delta_pct,
        "phase": row.phase,
        "seconds_elapsed": row.seconds_elapsed,
        "blocker_category": row.blocker_category,
        "rationale_he": row.rationale_he,
        "factors": factors,
    }


def tick_variants_for_window(
    repo: Repository,
    config: AppConfig,
    window: CryptoWindow,
    oracle,
    tokens,
    *,
    auto_sim: bool,
    has_liquidity_fn=None,
) -> dict[str, Any]:
    """Run every active variant on the same window snapshot."""
    ensure_population(repo)
    variants = repo.list_active_variants()[:MAX_ACTIVE_VARIANTS]
    stats: dict[str, Any] = {
        "variants": len(variants),
        "bets_placed": 0,
        "decisions": {},
        "decision_rows": [],
    }

    for variant in variants:
        params = variant_params_from_row(variant)
        cfg_override = params.to_cfg()
        phase = _phase_with_cfg(window, cfg_override).value
        already = repo.has_variant_bet_for_window(variant.id, window.asset.value, window.window_ts)

        decision = evaluate_window(
            window,
            oracle,
            tokens,
            config,
            already_bet=already,
            has_liquidity_fn=has_liquidity_fn,
            cfg_override=cfg_override,
        )
        stats["decisions"][variant.id] = decision

        executed = False
        execution_note: str | None = None
        bet_usd = float(params.bet_usd)

        if already:
            execution_note = "כבר בוצעה עסקה בגרסה זו בחלון"
        elif decision.action == DecisionAction.BET:
            if not auto_sim:
                execution_note = "סימולציה מושהה — לא מבצעים"
            elif variant.balance < bet_usd:
                execution_note = f"יתרת גרסה ${variant.balance:.2f} < ${bet_usd:.0f} נדרש"
            else:
                bet = _execute_variant_bet(
                    repo,
                    variant,
                    window,
                    decision,
                    bet_usd=bet_usd,
                    open_oracle_price=oracle.open_price,
                )
                if bet:
                    executed = True
                    stats["bets_placed"] += 1
        elif decision.action != DecisionAction.BET:
            execution_note = None

        from politrade.crypto.decision_rationale import attach_rationale, DecisionContext

        ctx = DecisionContext(
            seconds_elapsed=decision.seconds_elapsed,
            factors=list(decision.factors),
            blocker_category=decision.blocker_category,
        )
        attach_rationale(
            decision, ctx,
            executed=executed if decision.action == DecisionAction.BET else None,
            execution_note=execution_note or "",
        )

        row = repo.upsert_sim_variant_decision(
            variant_id=variant.id,
            variant_label=variant.label,
            asset=window.asset.value,
            window_ts=window.window_ts,
            slug=window.slug,
            action=decision.action.value,
            side=decision.side.value if decision.side else None,
            executed=executed,
            execution_note=execution_note,
            bet_usd=bet_usd if decision.action == DecisionAction.BET else None,
            entry_ask=decision.entry_ask,
            edge_pct=decision.edge_pct,
            oracle_delta_pct=oracle.delta_pct,
            phase=phase,
            seconds_elapsed=decision.seconds_elapsed,
            rationale_he=decision.rationale_he,
            factors_json=factors_to_json(decision.factors),
            blocker_category=decision.blocker_category,
        )
        stats["decision_rows"].append(variant_decision_to_dict(row))

    stats["aggregate"] = aggregate_variant_stats(stats["decision_rows"])
    return stats


def resolve_variant_bets_for_window(
    window_ts: int,
    config: AppConfig | None = None,
    repo: Repository | None = None,
) -> int:
    from politrade.config import AppConfig

    cfg = config or AppConfig()
    r = repo or Repository(cfg)
    feed = get_price_feed()
    now = int(time.time())
    if now < window_ts + WINDOW_SECONDS + 3:
        return 0

    by_variant: dict[int, list[tuple[bool, float, SimVariantBet]]] = {}
    resolved = 0

    for bet in r.get_variant_bets_for_window(window_ts):
        if bet.status != "open":
            continue
        result = _resolve_one_variant_bet(bet, feed, r)
        if result is None:
            continue
        won, pnl = result
        if won:
            r.adjust_variant_balance(bet.variant_id, bet.shares * 1.0)
        by_variant.setdefault(bet.variant_id, []).append((won, pnl, bet))
        resolved += 1

    for variant_id, results in by_variant.items():
        wins = sum(1 for won, _, _ in results if won)
        losses = len(results) - wins
        cycle_pnl = round(sum(pnl for _, pnl, _ in results), 4)
        r.record_variant_cycle_stats(
            variant_id,
            cycle_pnl=cycle_pnl,
            wins=wins,
            losses=losses,
            bets=len(results),
        )

    return resolved


def evolve_after_cycle(
    window_ts: int,
    repo: Repository,
    config: AppConfig | None = None,
) -> dict[str, Any]:
    """Rank variants, promote champion, mutate/replace underperformers."""
    variants = repo.list_active_variants()
    if len(variants) < 2:
        ensure_population(repo)
        variants = repo.list_active_variants()

    ranked = sorted(
        variants,
        key=lambda v: (v.rank_score, v.cumulative_pnl, v.balance),
        reverse=True,
    )
    if not ranked:
        return {"evolved": 0, "champion_id": None}

    champion = ranked[0]
    repo.set_champion_variant(champion.id)
    _sync_champion_to_main_ledger(repo, champion)

    rng = random.Random(window_ts)
    n = len(ranked)
    replace_count = max(1, n // 4)
    bottom = ranked[-replace_count:]
    top = ranked[: max(3, n // 3)]

    existing = {v.param_hash for v in variants}
    replaced = 0

    for loser in bottom:
        parent = rng.choice(top)
        parent_params = variant_params_from_row(parent)
        if rng.random() < 0.7:
            new_params = mutate_params(parent_params, rng)
        else:
            new_params = random_params(rng)

        attempts = 0
        while new_params.param_hash() in existing and attempts < 30:
            new_params = mutate_params(parent_params, rng)
            attempts += 1

        h = new_params.param_hash()
        if h in existing:
            continue

        repo.replace_sim_variant_params(
            loser.id,
            label=new_params.label(),
            params_json=json.dumps(new_params.to_cfg(), ensure_ascii=False),
            param_hash=h,
            reset_balance=loser.start_balance,
        )
        existing.discard(loser.param_hash)
        existing.add(h)
        replaced += 1

    # Light mutation on middle tier
    middle = ranked[replace_count:-replace_count] if n > replace_count * 2 else []
    for mid in middle[: max(0, n // 6)]:
        if rng.random() > 0.35:
            continue
        base = variant_params_from_row(mid)
        tweaked = mutate_params(base, rng)
        if tweaked.param_hash() in existing:
            continue
        repo.replace_sim_variant_params(
            mid.id,
            label=tweaked.label(),
            params_json=json.dumps(tweaked.to_cfg(), ensure_ascii=False),
            param_hash=tweaked.param_hash(),
        )
        existing.discard(mid.param_hash)
        existing.add(tweaked.param_hash())
        replaced += 1

    lesson = _format_evolution_lesson(ranked[:5], champion, replaced)
    log.info(
        "sim_variants_evolved",
        window_ts=window_ts,
        champion=champion.id,
        replaced=replaced,
    )
    return {
        "evolved": replaced,
        "champion_id": champion.id,
        "champion_label": champion.label,
        "champion_pnl": round(champion.cumulative_pnl, 2),
        "lesson_he": lesson,
        "leaderboard": [variant_to_dict(v) for v in ranked[:8]],
    }


def _sync_champion_to_main_ledger(repo: Repository, champion: SimVariant) -> None:
    repo.set_sim_balance(champion.balance)
    repo.set_state("sim_cumulative_pnl", str(round(champion.cumulative_pnl, 4)))


def _execute_variant_bet(
    repo: Repository,
    variant: SimVariant,
    window: CryptoWindow,
    decision: StrategyDecision,
    *,
    bet_usd: float,
    open_oracle_price: float | None,
) -> SimVariantBet | None:
    if decision.action.value != "bet" or not decision.side or bet_usd <= 0:
        return None

    entry_price = decision.entry_ask or 0.5
    if entry_price <= 0:
        entry_price = 0.5
    shares = bet_usd / entry_price
    token_id = decision.token_id or (
        window.up_token_id if decision.side == BetSide.UP else window.down_token_id
    )

    repo.adjust_variant_balance(variant.id, -bet_usd)
    from politrade.crypto.decision_rationale import factors_to_json

    return repo.create_variant_bet(
        variant_id=variant.id,
        asset=window.asset.value,
        window_ts=window.window_ts,
        slug=window.slug,
        market_title=window.title or None,
        side=decision.side.value,
        token_id=token_id,
        open_oracle_price=open_oracle_price,
        entry_price=entry_price,
        bet_usd=bet_usd,
        shares=shares,
        edge_pct=decision.edge_pct,
        decision_reason=decision.reason,
        rationale_he=decision.rationale_he,
        factors_json=factors_to_json(decision.factors),
        blocker_category=decision.blocker_category,
        seconds_at_entry=decision.seconds_elapsed,
    )


def _resolve_one_variant_bet(
    bet: SimVariantBet,
    feed,
    repo: Repository,
) -> tuple[bool, float] | None:
    from politrade.crypto.window import CryptoAsset, CryptoWindow

    try:
        asset = CryptoAsset(bet.asset)
    except ValueError:
        return None

    window = CryptoWindow(
        asset=asset,
        window_ts=bet.window_ts,
        slug=bet.slug,
        up_token_id=bet.token_id if bet.side == "up" else "",
        down_token_id=bet.token_id if bet.side == "down" else "",
    )
    snap = feed.get_snapshot(window)
    open_px = bet.open_oracle_price
    close_px = snap.close_price or snap.current_price or feed.get_price(asset)

    if open_px is None or close_px is None:
        return None

    up_wins = close_px >= open_px
    bet_side_up = bet.side.lower() == BetSide.UP.value
    won = (bet_side_up and up_wins) or (not bet_side_up and not up_wins)
    pnl = (bet.shares * 1.0 - bet.bet_usd) if won else -bet.bet_usd

    repo.resolve_variant_bet(
        bet.id,
        won=won,
        oracle_close_price=close_px,
        realized_pnl=round(pnl, 4),
    )
    feed.set_close_price(asset, bet.window_ts, close_px)
    return won, pnl


def _format_evolution_lesson(
    top: list[SimVariant],
    champion: SimVariant,
    replaced: int,
) -> str:
    lines = [
        f"אופטימיזציה: {len(top)} מובילים · {replaced} גרסאות הוחלפו/שונו",
        f"אלוף: {champion.label} · PnL ${champion.cumulative_pnl:+.2f} · יתרה ${champion.balance:.0f}",
    ]
    for i, v in enumerate(top[:3], 1):
        resolved = v.wins + v.losses
        wr = (v.wins / resolved * 100) if resolved else 0
        lines.append(f"{i}. {v.label[:60]}… · ${v.cumulative_pnl:+.2f} · WR {wr:.0f}%")
    return "\n".join(lines)


def params_to_user_settings(params: StrategyParams) -> dict[str, Any]:
    return {
        "crypto_bet_usd": params.bet_usd,
        "crypto_min_edge_pct": params.min_edge_pct,
        "crypto_max_entry_price": params.max_entry_price,
        "crypto_min_move_pct": params.min_move_pct,
        "crypto_no_bet_first_seconds": params.no_bet_first_seconds,
        "crypto_no_bet_last_seconds": params.no_bet_last_seconds,
        "crypto_strategy_mode": params.strategy_mode,
    }
