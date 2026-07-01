"""Database repository."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import Session, sessionmaker

from politrade.config import AppConfig
from politrade.paths import resolve_sqlite_url
from politrade.storage.models import (
    AuditLog,
    Base,
    BotState,
    CryptoBet,
    LeaderTradeSeen,
    OrderRecord,
    Position,
    PositionSnapshot,
    SimBet,
    SimCycle,
    SimDecision,
    SimLesson,
    SimVariant,
    SimVariantBet,
    SimVariantDecision,
    Trader,
)

DEFAULT_SIM_START_BALANCE = 1000.0


class Repository:
    def __init__(self, config: AppConfig | None = None) -> None:
        cfg = config or AppConfig()
        url = cfg.database_url
        if url.startswith("sqlite:"):
            url = resolve_sqlite_url(url)
        self.engine = create_engine(url, echo=False)
        Base.metadata.create_all(self.engine)
        self._migrate_schema()
        self.Session = sessionmaker(bind=self.engine)

    def _migrate_schema(self) -> None:
        insp = inspect(self.engine)
        if insp.has_table("positions"):
            cols = {c["name"] for c in insp.get_columns("positions")}
            if "market_title" not in cols:
                with self.engine.begin() as conn:
                    conn.execute(text("ALTER TABLE positions ADD COLUMN market_title VARCHAR(512)"))

        sim_migrations: dict[str, list[tuple[str, str]]] = {
            "sim_decisions": [
                ("rationale_he", "TEXT"),
                ("factors_json", "TEXT"),
                ("blocker_category", "VARCHAR(16)"),
                ("seconds_elapsed", "INTEGER"),
            ],
            "sim_variant_bets": [
                ("rationale_he", "TEXT"),
                ("factors_json", "TEXT"),
                ("blocker_category", "VARCHAR(16)"),
                ("seconds_at_entry", "INTEGER"),
                ("market_title", "VARCHAR(512)"),
            ],
            "sim_bets": [
                ("rationale_he", "TEXT"),
                ("factors_json", "TEXT"),
                ("blocker_category", "VARCHAR(16)"),
                ("seconds_at_entry", "INTEGER"),
                ("market_title", "VARCHAR(512)"),
            ],
        }
        for table, adds in sim_migrations.items():
            if not insp.has_table(table):
                continue
            cols = {c["name"] for c in insp.get_columns(table)}
            for col, typ in adds:
                if col not in cols:
                    with self.engine.begin() as conn:
                        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {typ}"))

    def session(self) -> Session:
        return self.Session()

    def audit(self, level: str, event: str, message: str) -> None:
        with self.session() as s:
            s.add(AuditLog(level=level, event=event, message=message))
            s.commit()

    def upsert_trader(
        self,
        address: str,
        *,
        username: str | None = None,
        score: float = 0.0,
        metrics: dict | None = None,
        is_active_leader: bool = False,
        is_blacklisted: bool = False,
    ) -> Trader:
        with self.session() as s:
            trader = s.get(Trader, address.lower())
            if trader is None:
                trader = Trader(address=address.lower())
                s.add(trader)
            trader.username = username or trader.username
            trader.score = score
            trader.metrics_json = json.dumps(metrics) if metrics else trader.metrics_json
            trader.is_active_leader = is_active_leader
            trader.is_blacklisted = is_blacklisted
            trader.last_scanned_at = datetime.now(timezone.utc)
            s.commit()
            s.refresh(trader)
            return trader

    def get_active_leaders(self) -> list[Trader]:
        with self.session() as s:
            return list(
                s.scalars(
                    select(Trader).where(
                        Trader.is_active_leader.is_(True),
                        Trader.is_blacklisted.is_(False),
                    )
                ).all()
            )

    def set_active_leaders(self, addresses: list[str]) -> None:
        addr_set = {a.lower() for a in addresses}
        with self.session() as s:
            for trader in s.scalars(select(Trader)).all():
                trader.is_active_leader = trader.address in addr_set
            s.commit()

    def is_trade_seen(self, trade_id: str) -> bool:
        with self.session() as s:
            return s.scalar(select(LeaderTradeSeen).where(LeaderTradeSeen.trade_id == trade_id)) is not None

    def mark_trade_seen(self, trade_id: str, leader_address: str) -> None:
        with self.session() as s:
            if not self.is_trade_seen(trade_id):
                s.add(LeaderTradeSeen(trade_id=trade_id, leader_address=leader_address.lower()))
                s.commit()

    def get_open_positions(self) -> list[Position]:
        with self.session() as s:
            return list(s.scalars(select(Position).where(Position.status == "open")).all())

    def count_open_positions(self) -> int:
        return len(self.get_open_positions())

    def has_open_position_for_market(self, market_id: str) -> bool:
        with self.session() as s:
            pos = s.scalar(
                select(Position).where(
                    Position.market_id == market_id,
                    Position.status == "open",
                )
            )
            return pos is not None

    def total_open_exposure(self) -> float:
        return sum(p.entry_cost_usd for p in self.get_open_positions())

    def create_position(
        self,
        *,
        token_id: str,
        market_id: str,
        leader_address: str,
        leader_trade_id: str | None,
        entry_price: float,
        entry_cost_usd: float,
        shares: float,
        market_title: str | None = None,
    ) -> Position:
        with self.session() as s:
            pos = Position(
                token_id=token_id,
                market_id=market_id,
                market_title=market_title,
                leader_address=leader_address.lower(),
                leader_trade_id=leader_trade_id,
                entry_price=entry_price,
                entry_cost_usd=entry_cost_usd,
                shares=shares,
                status="open",
            )
            s.add(pos)
            s.commit()
            s.refresh(pos)
            return pos

    def close_position(
        self,
        position_id: int,
        *,
        exit_price: float,
        realized_pnl: float,
        exit_reason: str,
    ) -> None:
        with self.session() as s:
            pos = s.get(Position, position_id)
            if pos is None:
                return
            pos.status = "closed"
            pos.closed_at = datetime.now(timezone.utc)
            pos.exit_price = exit_price
            pos.realized_pnl = realized_pnl
            pos.exit_reason = exit_reason
            s.commit()

    def record_order(
        self,
        *,
        position_id: int | None,
        token_id: str,
        side: str,
        amount: float,
        clob_response: str,
        status: str = "submitted",
    ) -> None:
        with self.session() as s:
            s.add(
                OrderRecord(
                    position_id=position_id,
                    token_id=token_id,
                    side=side,
                    amount=amount,
                    clob_response=clob_response,
                    status=status,
                )
            )
            s.commit()

    def get_state(self, key: str) -> str | None:
        with self.session() as s:
            row = s.get(BotState, key)
            return row.value if row else None

    def set_state(self, key: str, value: str) -> None:
        with self.session() as s:
            row = s.get(BotState, key)
            if row is None:
                row = BotState(key=key, value=value)
                s.add(row)
            else:
                row.value = value
            s.commit()

    def get_closed_positions_summary(self) -> dict:
        with self.session() as s:
            closed = list(s.scalars(select(Position).where(Position.status == "closed")).all())
        total_pnl = sum(p.realized_pnl or 0 for p in closed)
        wins = sum(1 for p in closed if (p.realized_pnl or 0) > 0)
        return {
            "closed_count": len(closed),
            "total_realized_pnl": total_pnl,
            "win_count": wins,
            "loss_count": len(closed) - wins,
        }

    def list_traders(self, *, active_only: bool = False) -> list[Trader]:
        with self.session() as s:
            q = select(Trader)
            if active_only:
                q = q.where(Trader.is_active_leader.is_(True))
            return list(s.scalars(q.order_by(Trader.score.desc())).all())

    def list_top_traders(self, limit: int = 5) -> list[Trader]:
        with self.session() as s:
            return list(
                s.scalars(
                    select(Trader)
                    .where(Trader.is_blacklisted.is_(False))
                    .order_by(Trader.score.desc())
                    .limit(limit)
                ).all()
            )

    def list_closed_positions(self, limit: int = 50) -> list[Position]:
        with self.session() as s:
            return list(
                s.scalars(
                    select(Position)
                    .where(Position.status == "closed")
                    .order_by(Position.id.desc())
                    .limit(limit)
                ).all()
            )

    def list_audit_logs(self, limit: int = 100) -> list[AuditLog]:
        with self.session() as s:
            return list(
                s.scalars(
                    select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)
                ).all()
            )

    def list_orders(self, limit: int = 100) -> list[OrderRecord]:
        with self.session() as s:
            return list(
                s.scalars(
                    select(OrderRecord).order_by(OrderRecord.created_at.desc()).limit(limit)
                ).all()
            )

    def record_snapshot(
        self,
        position_id: int,
        *,
        price: float,
        value_usd: float,
        pnl_usd: float,
        pnl_pct: float,
    ) -> None:
        with self.session() as s:
            s.add(
                PositionSnapshot(
                    position_id=position_id,
                    price=price,
                    value_usd=value_usd,
                    pnl_usd=pnl_usd,
                    pnl_pct=pnl_pct,
                )
            )
            s.commit()

    def list_snapshots(self, position_id: int, *, limit: int = 120) -> list[PositionSnapshot]:
        with self.session() as s:
            return list(
                s.scalars(
                    select(PositionSnapshot)
                    .where(PositionSnapshot.position_id == position_id)
                    .order_by(PositionSnapshot.recorded_at.desc())
                    .limit(limit)
                ).all()
            )

    def prune_snapshots(self, *, max_age_hours: int = 48) -> int:
        cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=max_age_hours)
        with self.session() as s:
            rows = list(
                s.scalars(
                    select(PositionSnapshot).where(PositionSnapshot.recorded_at < cutoff)
                ).all()
            )
            for row in rows:
                s.delete(row)
            s.commit()
            return len(rows)

    # --- Crypto bets ---

    def has_crypto_bet_for_window(self, asset: str, window_ts: int) -> bool:
        with self.session() as s:
            row = s.scalar(
                select(CryptoBet).where(
                    CryptoBet.asset == asset.lower(),
                    CryptoBet.window_ts == window_ts,
                    CryptoBet.status.not_in(("failed", "skipped")),
                )
            )
            return row is not None

    def create_crypto_bet(
        self,
        *,
        asset: str,
        window_ts: int,
        slug: str,
        market_title: str | None = None,
        side: str,
        token_id: str,
        condition_id: str,
        open_oracle_price: float | None,
        entry_price: float,
        bet_usd: float,
        shares: float,
        edge_pct: float | None = None,
        status: str = "open",
    ) -> CryptoBet:
        with self.session() as s:
            bet = CryptoBet(
                asset=asset.lower(),
                window_ts=window_ts,
                slug=slug,
                side=side.lower(),
                token_id=token_id,
                condition_id=condition_id,
                open_oracle_price=open_oracle_price,
                entry_price=entry_price,
                bet_usd=bet_usd,
                shares=shares,
                edge_pct=edge_pct,
                status=status,
            )
            s.add(bet)
            s.commit()
            s.refresh(bet)
            return bet

    def get_open_crypto_bets(self) -> list[CryptoBet]:
        with self.session() as s:
            return list(
                s.scalars(
                    select(CryptoBet).where(CryptoBet.status.in_(("open", "pending", "won")))
                ).all()
            )

    def get_crypto_bets_needing_resolution(self) -> list[CryptoBet]:
        with self.session() as s:
            return list(
                s.scalars(
                    select(CryptoBet).where(CryptoBet.status == "open")
                ).all()
            )

    def get_crypto_bets_needing_redeem(self) -> list[CryptoBet]:
        with self.session() as s:
            return list(
                s.scalars(
                    select(CryptoBet).where(CryptoBet.status == "won")
                ).all()
            )

    def resolve_crypto_bet(
        self,
        bet_id: int,
        *,
        won: bool,
        oracle_close_price: float | None,
        realized_pnl: float,
    ) -> None:
        with self.session() as s:
            bet = s.get(CryptoBet, bet_id)
            if bet is None:
                return
            bet.status = "won" if won else "lost"
            bet.oracle_close_price = oracle_close_price
            bet.realized_pnl = realized_pnl
            bet.resolved_at = datetime.now(timezone.utc)
            s.commit()

    def mark_crypto_bet_redeemed(self, bet_id: int) -> None:
        with self.session() as s:
            bet = s.get(CryptoBet, bet_id)
            if bet is None:
                return
            bet.status = "redeemed"
            s.commit()

    def mark_crypto_bet_failed(self, bet_id: int, reason: str) -> None:
        with self.session() as s:
            bet = s.get(CryptoBet, bet_id)
            if bet is None:
                return
            bet.status = "failed"
            bet.skip_reason = reason
            s.commit()

    def list_crypto_bets(self, limit: int = 50) -> list[CryptoBet]:
        with self.session() as s:
            return list(
                s.scalars(
                    select(CryptoBet).order_by(CryptoBet.id.desc()).limit(limit)
                ).all()
            )

    def crypto_bets_summary(self) -> dict:
        with self.session() as s:
            bets = list(s.scalars(select(CryptoBet)).all())
        resolved = [b for b in bets if b.status in ("won", "lost", "redeemed")]
        wins = sum(1 for b in resolved if b.status in ("won", "redeemed"))
        total_pnl = sum(b.realized_pnl or 0 for b in resolved)
        return {
            "total": len(bets),
            "resolved": len(resolved),
            "wins": wins,
            "losses": len(resolved) - wins,
            "total_pnl": round(total_pnl, 2),
        }

    # --- Simulation ---

    def get_sim_start_balance(self) -> float:
        raw = self.get_state("sim_start_balance")
        if raw is None:
            return DEFAULT_SIM_START_BALANCE
        try:
            return float(raw)
        except ValueError:
            return DEFAULT_SIM_START_BALANCE

    def set_sim_start_balance(self, amount: float) -> None:
        self.set_state("sim_start_balance", str(round(amount, 2)))

    def get_sim_balance(self) -> float:
        raw = self.get_state("sim_balance")
        if raw is None:
            start = self.get_sim_start_balance()
            self.set_state("sim_balance", str(start))
            return start
        try:
            return float(raw)
        except ValueError:
            return self.get_sim_start_balance()

    def set_sim_balance(self, amount: float) -> None:
        self.set_state("sim_balance", str(round(max(0.0, amount), 4)))

    def adjust_sim_balance(self, delta: float) -> float:
        new_bal = self.get_sim_balance() + delta
        self.set_sim_balance(new_bal)
        return new_bal

    def reset_sim_ledger(self, start_balance: float | None = None) -> float:
        start = start_balance if start_balance is not None else self.get_sim_start_balance()
        self.set_sim_start_balance(start)
        self.set_sim_balance(start)
        self.set_state("sim_cumulative_pnl", "0")
        with self.session() as s:
            for model in (
                SimBet, SimDecision, SimCycle, SimLesson,
                SimVariantBet, SimVariantDecision, SimVariant,
            ):
                for row in s.scalars(select(model)).all():
                    s.delete(row)
            s.commit()
        self.set_state("sim_variants_seeded", "0")
        return start

    def get_sim_cumulative_pnl(self) -> float:
        raw = self.get_state("sim_cumulative_pnl")
        if raw is None:
            return 0.0
        try:
            return float(raw)
        except ValueError:
            return 0.0

    def add_sim_cumulative_pnl(self, delta: float) -> float:
        total = self.get_sim_cumulative_pnl() + delta
        self.set_state("sim_cumulative_pnl", str(round(total, 4)))
        return total

    def upsert_sim_decision(
        self,
        *,
        asset: str,
        window_ts: int,
        slug: str,
        action: str,
        side: str | None,
        reason: str,
        phase: str,
        entry_ask: float | None,
        edge_pct: float | None,
        recommended_usd: float | None,
        confidence: float | None,
        oracle_delta_pct: float | None,
        entry_timing: str,
        worth_investing: bool,
        rationale_he: str | None = None,
        factors_json: str | None = None,
        blocker_category: str | None = None,
        seconds_elapsed: int | None = None,
    ) -> SimDecision:
        with self.session() as s:
            row = s.scalar(
                select(SimDecision).where(
                    SimDecision.slug == slug,
                    SimDecision.window_ts == window_ts,
                )
            )
            if row is None:
                row = SimDecision(
                    asset=asset.lower(),
                    window_ts=window_ts,
                    slug=slug,
                )
                s.add(row)
            row.action = action
            row.side = side
            row.reason = reason
            row.phase = phase
            row.entry_ask = entry_ask
            row.edge_pct = edge_pct
            row.recommended_usd = recommended_usd
            row.confidence = confidence
            row.oracle_delta_pct = oracle_delta_pct
            row.entry_timing = entry_timing
            row.worth_investing = worth_investing
            row.rationale_he = rationale_he
            row.factors_json = factors_json
            row.blocker_category = blocker_category
            row.seconds_elapsed = seconds_elapsed
            row.updated_at = datetime.now(timezone.utc)
            s.commit()
            s.refresh(row)
            return row

    def list_sim_decisions_for_window(self, window_ts: int) -> list[SimDecision]:
        with self.session() as s:
            return list(
                s.scalars(
                    select(SimDecision)
                    .where(SimDecision.window_ts == window_ts)
                    .order_by(SimDecision.asset)
                ).all()
            )

    def list_latest_sim_decisions(self, window_ts: int) -> list[SimDecision]:
        return self.list_sim_decisions_for_window(window_ts)

    def has_sim_bet_for_window(self, asset: str, window_ts: int) -> bool:
        with self.session() as s:
            row = s.scalar(
                select(SimBet).where(
                    SimBet.asset == asset.lower(),
                    SimBet.window_ts == window_ts,
                    SimBet.status.not_in(("failed",)),
                )
            )
            return row is not None

    def create_sim_bet(
        self,
        *,
        asset: str,
        window_ts: int,
        slug: str,
        market_title: str | None = None,
        side: str,
        token_id: str,
        open_oracle_price: float | None,
        entry_price: float,
        bet_usd: float,
        shares: float,
        edge_pct: float | None = None,
        decision_reason: str = "",
        rationale_he: str | None = None,
        factors_json: str | None = None,
        blocker_category: str | None = None,
        seconds_at_entry: int | None = None,
    ) -> SimBet:
        with self.session() as s:
            bet = SimBet(
                asset=asset.lower(),
                window_ts=window_ts,
                slug=slug,
                market_title=market_title,
                side=side.lower(),
                token_id=token_id,
                open_oracle_price=open_oracle_price,
                entry_price=entry_price,
                bet_usd=bet_usd,
                shares=shares,
                edge_pct=edge_pct,
                decision_reason=decision_reason,
                rationale_he=rationale_he,
                factors_json=factors_json,
                blocker_category=blocker_category,
                seconds_at_entry=seconds_at_entry,
                status="open",
            )
            s.add(bet)
            s.commit()
            s.refresh(bet)
            return bet

    def get_open_sim_bets(self) -> list[SimBet]:
        with self.session() as s:
            return list(
                s.scalars(select(SimBet).where(SimBet.status == "open")).all()
            )

    def get_sim_bets_for_window(self, window_ts: int) -> list[SimBet]:
        with self.session() as s:
            return list(
                s.scalars(
                    select(SimBet).where(SimBet.window_ts == window_ts)
                ).all()
            )

    def resolve_sim_bet(
        self,
        bet_id: int,
        *,
        won: bool,
        oracle_close_price: float | None,
        realized_pnl: float,
    ) -> None:
        with self.session() as s:
            bet = s.get(SimBet, bet_id)
            if bet is None:
                return
            bet.status = "won" if won else "lost"
            bet.oracle_close_price = oracle_close_price
            bet.realized_pnl = realized_pnl
            bet.resolved_at = datetime.now(timezone.utc)
            s.commit()

    def list_sim_bets(self, limit: int = 50) -> list[SimBet]:
        with self.session() as s:
            return list(
                s.scalars(
                    select(SimBet).order_by(SimBet.id.desc()).limit(limit)
                ).all()
            )

    def list_all_sim_bets(self) -> list[SimBet]:
        with self.session() as s:
            return list(s.scalars(select(SimBet).order_by(SimBet.id)).all())

    def list_all_variant_bets(self) -> list[SimVariantBet]:
        with self.session() as s:
            return list(s.scalars(select(SimVariantBet).order_by(SimVariantBet.id)).all())

    def sim_bets_summary(self) -> dict:
        with self.session() as s:
            bets = list(s.scalars(select(SimBet)).all())
        resolved = [b for b in bets if b.status in ("won", "lost")]
        wins = sum(1 for b in resolved if b.status == "won")
        total_pnl = sum(b.realized_pnl or 0 for b in resolved)
        open_bets = [b for b in bets if b.status == "open"]
        return {
            "total": len(bets),
            "open": len(open_bets),
            "resolved": len(resolved),
            "wins": wins,
            "losses": len(resolved) - wins,
            "total_pnl": round(total_pnl, 2),
        }

    def create_sim_cycle(self, **kwargs) -> SimCycle:
        with self.session() as s:
            cycle = SimCycle(**kwargs)
            s.add(cycle)
            s.commit()
            s.refresh(cycle)
            return cycle

    def get_sim_cycle(self, window_ts: int) -> SimCycle | None:
        with self.session() as s:
            return s.scalar(select(SimCycle).where(SimCycle.window_ts == window_ts))

    def list_sim_cycles(self, limit: int = 30) -> list[SimCycle]:
        with self.session() as s:
            return list(
                s.scalars(
                    select(SimCycle).order_by(SimCycle.window_ts.desc()).limit(limit)
                ).all()
            )

    def create_sim_lesson(self, **kwargs) -> SimLesson:
        with self.session() as s:
            lesson = SimLesson(**kwargs)
            s.add(lesson)
            s.commit()
            s.refresh(lesson)
            return lesson

    def list_sim_lessons(self, limit: int = 20) -> list[SimLesson]:
        with self.session() as s:
            return list(
                s.scalars(
                    select(SimLesson).order_by(SimLesson.id.desc()).limit(limit)
                ).all()
            )

    # --- Parallel strategy variants ---

    def is_variants_seeded(self) -> bool:
        return self.get_state("sim_variants_seeded") == "1"

    def mark_variants_seeded(self) -> None:
        self.set_state("sim_variants_seeded", "1")

    def create_sim_variant(
        self,
        *,
        label: str,
        params_json: str,
        param_hash: str,
        start_balance: float,
        is_champion: bool = False,
    ) -> SimVariant:
        with self.session() as s:
            variant = SimVariant(
                label=label,
                params_json=params_json,
                param_hash=param_hash,
                start_balance=start_balance,
                balance=start_balance,
                is_champion=is_champion,
            )
            s.add(variant)
            s.commit()
            s.refresh(variant)
            return variant

    def list_active_variants(self) -> list[SimVariant]:
        with self.session() as s:
            return list(
                s.scalars(
                    select(SimVariant)
                    .where(SimVariant.is_active.is_(True))
                    .order_by(SimVariant.rank_score.desc(), SimVariant.id)
                ).all()
            )

    def list_variants_leaderboard(self, limit: int = 12) -> list[SimVariant]:
        with self.session() as s:
            return list(
                s.scalars(
                    select(SimVariant)
                    .where(SimVariant.is_active.is_(True))
                    .order_by(SimVariant.rank_score.desc(), SimVariant.cumulative_pnl.desc())
                    .limit(limit)
                ).all()
            )

    def get_champion_variant(self) -> SimVariant | None:
        with self.session() as s:
            row = s.scalar(
                select(SimVariant).where(
                    SimVariant.is_champion.is_(True),
                    SimVariant.is_active.is_(True),
                )
            )
            if row:
                return row
            return s.scalar(
                select(SimVariant)
                .where(SimVariant.is_active.is_(True))
                .order_by(SimVariant.rank_score.desc(), SimVariant.id)
                .limit(1)
            )

    def set_champion_variant(self, variant_id: int) -> None:
        with self.session() as s:
            for v in s.scalars(select(SimVariant)).all():
                v.is_champion = v.id == variant_id
            s.commit()

    def update_sim_variant(self, variant_id: int, **fields) -> None:
        with self.session() as s:
            row = s.get(SimVariant, variant_id)
            if row is None:
                return
            for key, val in fields.items():
                setattr(row, key, val)
            s.commit()

    def replace_sim_variant_params(
        self,
        variant_id: int,
        *,
        label: str,
        params_json: str,
        param_hash: str,
        reset_balance: float | None = None,
    ) -> None:
        with self.session() as s:
            row = s.get(SimVariant, variant_id)
            if row is None:
                return
            row.label = label
            row.params_json = params_json
            row.param_hash = param_hash
            if reset_balance is not None:
                row.start_balance = reset_balance
                row.balance = reset_balance
                row.cumulative_pnl = 0.0
                row.wins = 0
                row.losses = 0
                row.bets_total = 0
                row.cycles_count = 0
                row.last_cycle_pnl = 0.0
                row.rank_score = 0.0
            s.commit()

    def has_variant_bet_for_window(self, variant_id: int, asset: str, window_ts: int) -> bool:
        with self.session() as s:
            row = s.scalar(
                select(SimVariantBet).where(
                    SimVariantBet.variant_id == variant_id,
                    SimVariantBet.asset == asset.lower(),
                    SimVariantBet.window_ts == window_ts,
                    SimVariantBet.status.not_in(("failed",)),
                )
            )
            return row is not None

    def create_variant_bet(
        self,
        *,
        variant_id: int,
        asset: str,
        window_ts: int,
        slug: str,
        market_title: str | None = None,
        side: str,
        token_id: str,
        open_oracle_price: float | None,
        entry_price: float,
        bet_usd: float,
        shares: float,
        edge_pct: float | None = None,
        decision_reason: str = "",
        rationale_he: str | None = None,
        factors_json: str | None = None,
        blocker_category: str | None = None,
        seconds_at_entry: int | None = None,
    ) -> SimVariantBet:
        with self.session() as s:
            bet = SimVariantBet(
                variant_id=variant_id,
                asset=asset.lower(),
                window_ts=window_ts,
                slug=slug,
                market_title=market_title,
                side=side.lower(),
                token_id=token_id,
                open_oracle_price=open_oracle_price,
                entry_price=entry_price,
                bet_usd=bet_usd,
                shares=shares,
                edge_pct=edge_pct,
                decision_reason=decision_reason,
                rationale_he=rationale_he,
                factors_json=factors_json,
                blocker_category=blocker_category,
                seconds_at_entry=seconds_at_entry,
                status="open",
            )
            s.add(bet)
            s.commit()
            s.refresh(bet)
            return bet

    def adjust_variant_balance(self, variant_id: int, delta: float) -> float:
        with self.session() as s:
            row = s.get(SimVariant, variant_id)
            if row is None:
                return 0.0
            row.balance = round(max(0.0, row.balance + delta), 4)
            s.commit()
            return row.balance

    def get_variant_bets_for_window(self, window_ts: int) -> list[SimVariantBet]:
        with self.session() as s:
            return list(
                s.scalars(
                    select(SimVariantBet).where(SimVariantBet.window_ts == window_ts)
                ).all()
            )

    def resolve_variant_bet(
        self,
        bet_id: int,
        *,
        won: bool,
        oracle_close_price: float | None,
        realized_pnl: float,
    ) -> None:
        with self.session() as s:
            bet = s.get(SimVariantBet, bet_id)
            if bet is None:
                return
            bet.status = "won" if won else "lost"
            bet.oracle_close_price = oracle_close_price
            bet.realized_pnl = realized_pnl
            bet.resolved_at = datetime.now(timezone.utc)
            s.commit()

    def record_variant_cycle_stats(
        self,
        variant_id: int,
        *,
        cycle_pnl: float,
        wins: int,
        losses: int,
        bets: int,
    ) -> None:
        with self.session() as s:
            row = s.get(SimVariant, variant_id)
            if row is None:
                return
            row.last_cycle_pnl = round(cycle_pnl, 4)
            row.cumulative_pnl = round(row.cumulative_pnl + cycle_pnl, 4)
            row.wins += wins
            row.losses += losses
            row.bets_total += bets
            row.cycles_count += 1
            resolved = row.wins + row.losses
            wr = (row.wins / resolved * 100) if resolved else 50.0
            bal_ratio = row.balance / row.start_balance if row.start_balance else 1.0
            row.rank_score = round(
                row.cumulative_pnl + wr * 0.5 + (bal_ratio - 1.0) * 100.0,
                4,
            )
            s.commit()

    def upsert_sim_variant_decision(
        self,
        *,
        variant_id: int,
        variant_label: str,
        asset: str,
        window_ts: int,
        slug: str,
        action: str,
        side: str | None,
        executed: bool,
        execution_note: str | None,
        bet_usd: float | None,
        entry_ask: float | None,
        edge_pct: float | None,
        oracle_delta_pct: float | None,
        phase: str,
        seconds_elapsed: int | None,
        rationale_he: str | None,
        factors_json: str | None,
        blocker_category: str | None,
    ) -> SimVariantDecision:
        with self.session() as s:
            row = s.scalar(
                select(SimVariantDecision).where(
                    SimVariantDecision.variant_id == variant_id,
                    SimVariantDecision.slug == slug,
                    SimVariantDecision.window_ts == window_ts,
                )
            )
            if row is None:
                row = SimVariantDecision(
                    variant_id=variant_id,
                    asset=asset.lower(),
                    window_ts=window_ts,
                    slug=slug,
                    variant_label=variant_label,
                )
                s.add(row)
            row.action = action
            row.side = side
            row.executed = executed
            row.execution_note = execution_note
            row.bet_usd = bet_usd
            row.entry_ask = entry_ask
            row.edge_pct = edge_pct
            row.oracle_delta_pct = oracle_delta_pct
            row.phase = phase
            row.seconds_elapsed = seconds_elapsed
            row.rationale_he = rationale_he
            row.factors_json = factors_json
            row.blocker_category = blocker_category
            row.variant_label = variant_label
            row.updated_at = datetime.now(timezone.utc)
            s.commit()
            s.refresh(row)
            return row

    def list_variant_decisions_for_slug(
        self,
        window_ts: int,
        slug: str,
    ) -> list[SimVariantDecision]:
        with self.session() as s:
            return list(
                s.scalars(
                    select(SimVariantDecision)
                    .where(
                        SimVariantDecision.window_ts == window_ts,
                        SimVariantDecision.slug == slug,
                    )
                    .order_by(SimVariantDecision.executed.desc(), SimVariantDecision.variant_id)
                ).all()
            )

    def list_variant_decisions_for_window(self, window_ts: int) -> list[SimVariantDecision]:
        with self.session() as s:
            return list(
                s.scalars(
                    select(SimVariantDecision)
                    .where(SimVariantDecision.window_ts == window_ts)
                    .order_by(SimVariantDecision.slug, SimVariantDecision.variant_id)
                ).all()
            )

    def list_recent_variant_bets(self, limit: int = 40) -> list[SimVariantBet]:
        with self.session() as s:
            return list(
                s.scalars(
                    select(SimVariantBet).order_by(SimVariantBet.id.desc()).limit(limit)
                ).all()
            )

