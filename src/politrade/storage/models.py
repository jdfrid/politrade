"""SQLAlchemy models."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Trader(Base):
    __tablename__ = "traders"

    address: Mapped[str] = mapped_column(String(66), primary_key=True)
    username: Mapped[str | None] = mapped_column(String(128), nullable=True)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    metrics_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active_leader: Mapped[bool] = mapped_column(Boolean, default=False)
    is_blacklisted: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_scanned_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class LeaderTradeSeen(Base):
    __tablename__ = "leader_trades_seen"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trade_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    leader_address: Mapped[str] = mapped_column(String(66), index=True)
    seen_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Position(Base):
    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    token_id: Mapped[str] = mapped_column(String(128), index=True)
    market_id: Mapped[str] = mapped_column(String(128))
    market_title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    leader_address: Mapped[str] = mapped_column(String(66))
    leader_trade_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    side: Mapped[str] = mapped_column(String(8), default="BUY")
    entry_price: Mapped[float] = mapped_column(Float)
    entry_cost_usd: Mapped[float] = mapped_column(Float)
    shares: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(16), default="open")  # open | closed
    opened_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    exit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    realized_pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    exit_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)


class PositionSnapshot(Base):
    __tablename__ = "position_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    position_id: Mapped[int] = mapped_column(Integer, index=True)
    price: Mapped[float] = mapped_column(Float)
    value_usd: Mapped[float] = mapped_column(Float)
    pnl_usd: Mapped[float] = mapped_column(Float)
    pnl_pct: Mapped[float] = mapped_column(Float)
    recorded_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


class OrderRecord(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    position_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    token_id: Mapped[str] = mapped_column(String(128))
    side: Mapped[str] = mapped_column(String(8))
    amount: Mapped[float] = mapped_column(Float)
    clob_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="submitted")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    level: Mapped[str] = mapped_column(String(16))
    event: Mapped[str] = mapped_column(String(64))
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class BotState(Base):
    __tablename__ = "bot_state"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class CryptoBet(Base):
    __tablename__ = "crypto_bets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    asset: Mapped[str] = mapped_column(String(8), index=True)
    window_ts: Mapped[int] = mapped_column(Integer, index=True)
    slug: Mapped[str] = mapped_column(String(128))
    market_title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    side: Mapped[str] = mapped_column(String(8))
    token_id: Mapped[str] = mapped_column(String(128))
    condition_id: Mapped[str] = mapped_column(String(128), default="")
    open_oracle_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    entry_price: Mapped[float] = mapped_column(Float)
    bet_usd: Mapped[float] = mapped_column(Float)
    shares: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(16), default="open")
    oracle_close_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    realized_pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    skip_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    edge_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class SimBet(Base):
    __tablename__ = "sim_bets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    asset: Mapped[str] = mapped_column(String(8), index=True)
    window_ts: Mapped[int] = mapped_column(Integer, index=True)
    slug: Mapped[str] = mapped_column(String(128))
    market_title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    side: Mapped[str] = mapped_column(String(8))
    token_id: Mapped[str] = mapped_column(String(128), default="")
    open_oracle_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    entry_price: Mapped[float] = mapped_column(Float)
    bet_usd: Mapped[float] = mapped_column(Float)
    shares: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(16), default="open")
    oracle_close_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    realized_pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    edge_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    decision_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    rationale_he: Mapped[str | None] = mapped_column(Text, nullable=True)
    factors_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    blocker_category: Mapped[str | None] = mapped_column(String(16), nullable=True)
    seconds_at_entry: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class SimVariantDecision(Base):
    __tablename__ = "sim_variant_decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    variant_id: Mapped[int] = mapped_column(Integer, index=True)
    asset: Mapped[str] = mapped_column(String(8), index=True)
    window_ts: Mapped[int] = mapped_column(Integer, index=True)
    slug: Mapped[str] = mapped_column(String(128), index=True)
    action: Mapped[str] = mapped_column(String(8))
    side: Mapped[str | None] = mapped_column(String(8), nullable=True)
    executed: Mapped[bool] = mapped_column(Boolean, default=False)
    execution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    bet_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    entry_ask: Mapped[float | None] = mapped_column(Float, nullable=True)
    edge_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    oracle_delta_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    phase: Mapped[str] = mapped_column(String(16), default="")
    seconds_elapsed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rationale_he: Mapped[str | None] = mapped_column(Text, nullable=True)
    factors_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    blocker_category: Mapped[str | None] = mapped_column(String(16), nullable=True)
    variant_label: Mapped[str] = mapped_column(String(256), default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class SimDecision(Base):
    __tablename__ = "sim_decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    asset: Mapped[str] = mapped_column(String(8), index=True)
    window_ts: Mapped[int] = mapped_column(Integer, index=True)
    slug: Mapped[str] = mapped_column(String(128), index=True)
    action: Mapped[str] = mapped_column(String(8))
    side: Mapped[str | None] = mapped_column(String(8), nullable=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    phase: Mapped[str] = mapped_column(String(16), default="")
    entry_ask: Mapped[float | None] = mapped_column(Float, nullable=True)
    edge_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    recommended_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    oracle_delta_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    entry_timing: Mapped[str | None] = mapped_column(String(128), nullable=True)
    worth_investing: Mapped[bool] = mapped_column(Boolean, default=False)
    rationale_he: Mapped[str | None] = mapped_column(Text, nullable=True)
    factors_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    blocker_category: Mapped[str | None] = mapped_column(String(16), nullable=True)
    seconds_elapsed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class SimCycle(Base):
    __tablename__ = "sim_cycles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    window_ts: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    markets_total: Mapped[int] = mapped_column(Integer, default=0)
    bets_taken: Mapped[int] = mapped_column(Integer, default=0)
    bets_skipped: Mapped[int] = mapped_column(Integer, default=0)
    waits: Mapped[int] = mapped_column(Integer, default=0)
    wins: Mapped[int] = mapped_column(Integer, default=0)
    losses: Mapped[int] = mapped_column(Integer, default=0)
    cycle_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    cumulative_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    win_rate: Mapped[float] = mapped_column(Float, default=0.0)
    win_rate_delta: Mapped[float | None] = mapped_column(Float, nullable=True)
    pnl_delta: Mapped[float | None] = mapped_column(Float, nullable=True)
    summary_he: Mapped[str] = mapped_column(Text, default="")
    lessons_he: Mapped[str] = mapped_column(Text, default="")
    params_before: Mapped[str | None] = mapped_column(Text, nullable=True)
    params_after: Mapped[str | None] = mapped_column(Text, nullable=True)
    readiness_score: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class SimLesson(Base):
    __tablename__ = "sim_lessons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    window_ts: Mapped[int] = mapped_column(Integer, index=True)
    lessons_he: Mapped[str] = mapped_column(Text, default="")
    params_before: Mapped[str | None] = mapped_column(Text, nullable=True)
    params_after: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class SimVariant(Base):
    __tablename__ = "sim_variants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    label: Mapped[str] = mapped_column(String(256), default="")
    params_json: Mapped[str] = mapped_column(Text, default="{}")
    param_hash: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    start_balance: Mapped[float] = mapped_column(Float, default=1000.0)
    balance: Mapped[float] = mapped_column(Float, default=1000.0)
    cumulative_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    wins: Mapped[int] = mapped_column(Integer, default=0)
    losses: Mapped[int] = mapped_column(Integer, default=0)
    bets_total: Mapped[int] = mapped_column(Integer, default=0)
    cycles_count: Mapped[int] = mapped_column(Integer, default=0)
    last_cycle_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    rank_score: Mapped[float] = mapped_column(Float, default=0.0)
    is_champion: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class SimVariantBet(Base):
    __tablename__ = "sim_variant_bets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    variant_id: Mapped[int] = mapped_column(Integer, index=True)
    asset: Mapped[str] = mapped_column(String(8), index=True)
    window_ts: Mapped[int] = mapped_column(Integer, index=True)
    slug: Mapped[str] = mapped_column(String(128))
    market_title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    side: Mapped[str] = mapped_column(String(8))
    token_id: Mapped[str] = mapped_column(String(128), default="")
    open_oracle_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    entry_price: Mapped[float] = mapped_column(Float)
    bet_usd: Mapped[float] = mapped_column(Float)
    shares: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(16), default="open")
    oracle_close_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    realized_pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    edge_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    decision_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    rationale_he: Mapped[str | None] = mapped_column(Text, nullable=True)
    factors_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    blocker_category: Mapped[str | None] = mapped_column(String(16), nullable=True)
    seconds_at_entry: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
