"""Filter copy signals before execution."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from politrade.api.clob_client import ClobClientWrapper
from politrade.api.data_client import DataClient
from politrade.config import AppConfig
from politrade.storage.repository import Repository


@dataclass
class CopySignal:
    leader_address: str
    market_id: str
    token_id: str
    side: Literal["BUY"]
    leader_price: float
    leader_size_usd: float
    leader_trade_id: str
    detected_at: datetime


class TradeSelector:
    def __init__(
        self,
        config: AppConfig | None = None,
        repo: Repository | None = None,
        data: DataClient | None = None,
        clob: ClobClientWrapper | None = None,
    ) -> None:
        self.config = config or AppConfig()
        self.repo = repo or Repository(self.config)
        self.data = data or DataClient(self.config)
        self.clob = clob or ClobClientWrapper(self.config)

    def build_signal(self, trade: dict, leader_address: str) -> CopySignal | None:
        """Build signal from raw trade without filter checks."""
        token_id = self._extract_token_id(trade)
        market_id = self._extract_market_id(trade)
        if not token_id or not market_id:
            return None
        leader = leader_address.lower()
        return CopySignal(
            leader_address=leader,
            market_id=market_id,
            token_id=token_id,
            side="BUY",
            leader_price=float(trade.get("price", 0) or 0),
            leader_size_usd=self._trade_usd(trade),
            leader_trade_id=self._trade_id(trade),
            detected_at=datetime.now(timezone.utc),
        )

    def evaluate(self, trade: dict, leader_score: float, *, manual: bool = False) -> CopySignal | None:
        copy_cfg = self.config.copy
        risk_cfg = self.config.risk

        if not manual:
            min_score = float(copy_cfg.get("min_leader_score", 70))
            if leader_score < min_score:
                return None

        side = str(trade.get("side", "")).upper()
        if side != "BUY":
            return None

        size_usd = self._trade_usd(trade)
        if size_usd < float(copy_cfg.get("min_leader_trade_usd", 10)):
            return None

        token_id = self._extract_token_id(trade)
        market_id = self._extract_market_id(trade)
        if not token_id or not market_id:
            return None

        if self.repo.has_open_position_for_market(market_id):
            return None

        if self.repo.count_open_positions() >= int(risk_cfg.get("max_open_positions", 5)):
            return None

        if not self._market_active(market_id):
            return None

        if not manual:
            max_spread = float(risk_cfg.get("max_spread_pct", 3))
            if self.clob.is_configured:
                spread = self.clob.get_spread_pct(token_id)
                if spread is not None and spread > max_spread:
                    return None

        leader = str(trade.get("proxyWallet") or trade.get("user") or trade.get("maker", "")).lower()
        return self.build_signal(trade, leader)

    def _market_active(self, market_id: str) -> bool:
        market = self.data.get_market(market_id)
        if market is None:
            return True
        if market.get("closed") is True:
            return False
        if market.get("active") is False:
            return False
        return True

    @staticmethod
    def _trade_usd(trade: dict) -> float:
        for key in ("usdcSize", "usdc_size", "size", "amount"):
            val = trade.get(key)
            if val is not None:
                try:
                    return abs(float(val))
                except (TypeError, ValueError):
                    pass
        price = float(trade.get("price", 0) or 0)
        size = float(trade.get("size", 0) or 0)
        return abs(price * size)

    @staticmethod
    def _extract_token_id(trade: dict) -> str | None:
        for key in ("asset", "asset_id", "tokenId", "token_id"):
            val = trade.get(key)
            if val:
                return str(val)
        return None

    @staticmethod
    def _extract_market_id(trade: dict) -> str | None:
        for key in ("conditionId", "condition_id", "market", "market_id"):
            val = trade.get(key)
            if val:
                return str(val)
        return None

    @staticmethod
    def _trade_id(trade: dict) -> str:
        for key in ("id", "tradeId", "trade_id", "transactionHash"):
            val = trade.get(key)
            if val:
                return str(val)
        return f"{trade.get('timestamp')}_{trade.get('asset')}_{trade.get('side')}"
