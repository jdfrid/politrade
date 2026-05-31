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
