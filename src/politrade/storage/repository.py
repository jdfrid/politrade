"""Database repository."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from politrade.config import AppConfig
from politrade.paths import resolve_sqlite_url
from politrade.storage.models import (
    AuditLog,
    Base,
    BotState,
    LeaderTradeSeen,
    OrderRecord,
    Position,
    Trader,
)


class Repository:
    def __init__(self, config: AppConfig | None = None) -> None:
        cfg = config or AppConfig()
        url = cfg.database_url
        if url.startswith("sqlite:"):
            url = resolve_sqlite_url(url)
        self.engine = create_engine(url, echo=False)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

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
    ) -> Position:
        with self.session() as s:
            pos = Position(
                token_id=token_id,
                market_id=market_id,
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
