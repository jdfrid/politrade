"""Poll leader trades and emit copy signals."""

from __future__ import annotations

from politrade.api.data_client import DataClient
from politrade.config import AppConfig
from politrade.logging_setup import get_logger
from politrade.signals.trade_selector import CopySignal, TradeSelector
from politrade.storage.repository import Repository

log = get_logger(__name__)


class CopyDetector:
    def __init__(
        self,
        config: AppConfig | None = None,
        data: DataClient | None = None,
        repo: Repository | None = None,
        selector: TradeSelector | None = None,
    ) -> None:
        self.config = config or AppConfig()
        self.data = data or DataClient(self.config)
        self.repo = repo or Repository(self.config)
        self.selector = selector or TradeSelector(self.config, self.repo, self.data)

    def poll(self) -> list[CopySignal]:
        signals: list[CopySignal] = []
        leaders = self.repo.get_active_leaders()

        for leader in leaders:
            try:
                trades = self.data.get_trades(leader.address, limit=20)
            except Exception as exc:
                log.warning("poll_trades_failed", leader=leader.address, error=str(exc))
                continue

            for trade in trades:
                trade_id = self.selector._trade_id(trade)
                if self.repo.is_trade_seen(trade_id):
                    continue

                signal = self.selector.evaluate(trade, leader.score)
                self.repo.mark_trade_seen(trade_id, leader.address)

                if signal:
                    log.info(
                        "copy_signal",
                        leader=leader.address,
                        market=signal.market_id,
                        size=signal.leader_size_usd,
                    )
                    signals.append(signal)

        return signals
