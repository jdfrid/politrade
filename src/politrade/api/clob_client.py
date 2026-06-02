"""Polymarket CLOB V2 client wrapper."""

from __future__ import annotations

import json
from typing import Any

from py_clob_client_v2.client import ClobClient
from py_clob_client_v2.clob_types import ApiCreds, MarketOrderArgsV2, OrderType

from politrade.config import AppConfig
from politrade.logging_setup import get_logger

log = get_logger(__name__)


class ClobClientWrapper:
    """Wraps py-clob-client-v2 for trading operations."""

    def __init__(self, config: AppConfig | None = None) -> None:
        self.config = config or AppConfig()
        self._client: ClobClient | None = None

    @property
    def is_configured(self) -> bool:
        return self.config.clob_configured

    def _ensure_client(self) -> ClobClient:
        if self._client is not None:
            return self._client
        if not self.is_configured:
            raise RuntimeError(
                "CLOB client not configured. Set PRIVATE_KEY and FUNDER_ADDRESS in .env"
            )

        api = self.config.api
        creds = self._load_or_create_creds()
        self._client = ClobClient(
            api.get("clob_host", "https://clob.polymarket.com"),
            chain_id=int(api.get("chain_id", 137)),
            key=self.config.private_key,
            creds=creds,
            signature_type=self.config.signature_type,
            funder=self.config.funder_address,
            retry_on_error=True,
        )
        return self._client

    def _load_or_create_creds(self) -> ApiCreds:
        path = self.config.creds_path
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            return ApiCreds(
                api_key=data["apiKey"],
                api_secret=data["secret"],
                api_passphrase=data["passphrase"],
            )

        api = self.config.api
        raw = ClobClient(
            api.get("clob_host", "https://clob.polymarket.com"),
            chain_id=int(api.get("chain_id", 137)),
            key=self.config.private_key,
            signature_type=self.config.signature_type,
            funder=self.config.funder_address,
        )
        creds = raw.create_or_derive_api_key()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "apiKey": creds.api_key,
                    "secret": creds.api_secret,
                    "passphrase": creds.api_passphrase,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        log.info("clob_api_creds_saved", path=str(path))
        return creds

    def reset_stored_creds(self) -> None:
        """Delete cached CLOB API creds (needed after funder/signature_type change)."""
        self._client = None
        path = self.config.creds_path
        if path.exists():
            path.unlink()
            log.info("clob_api_creds_deleted", path=str(path))

    def get_mid_price(self, token_id: str) -> float | None:
        client = self._ensure_client()
        try:
            mid = client.get_midpoint(token_id)
            if isinstance(mid, dict):
                val = mid.get("mid") or mid.get("price")
                return float(val) if val is not None else None
            return float(mid)
        except Exception as exc:
            log.warning("get_mid_price_failed", token_id=token_id, error=str(exc))
            return self._mid_from_book(token_id)

    def _mid_from_book(self, token_id: str) -> float | None:
        client = self._ensure_client()
        try:
            book = client.get_order_book(token_id)
            bids = book.get("bids", []) if isinstance(book, dict) else (book.bids or [])
            asks = book.get("asks", []) if isinstance(book, dict) else (book.asks or [])
            if not bids or not asks:
                return None
            bid = float(bids[0]["price"])
            ask = float(asks[0]["price"])
            return (bid + ask) / 2
        except Exception:
            return None

    def get_spread_pct(self, token_id: str) -> float | None:
        client = self._ensure_client()
        try:
            book = client.get_order_book(token_id)
            bids = book.get("bids", []) if isinstance(book, dict) else (book.bids or [])
            asks = book.get("asks", []) if isinstance(book, dict) else (book.asks or [])
            if not bids or not asks:
                return None
            bid = float(bids[0]["price"])
            ask = float(asks[0]["price"])
            mid = (bid + ask) / 2
            if mid <= 0:
                return None
            return ((ask - bid) / mid) * 100
        except Exception:
            return None

    def get_balance(self) -> float | None:
        client = self._ensure_client()
        try:
            bal = client.get_balance_allowance()
            if isinstance(bal, dict):
                return float(bal.get("balance", bal.get("available", 0)))
            return float(bal)
        except Exception as exc:
            log.warning("get_balance_failed", error=str(exc))
            return None

    def market_buy(self, token_id: str, amount_usd: float) -> dict[str, Any]:
        return self._market_order(token_id, "BUY", amount_usd)

    def market_sell(self, token_id: str, size_shares: float) -> dict[str, Any]:
        return self._market_order(token_id, "SELL", size_shares)

    def _market_order(self, token_id: str, side: str, amount: float) -> dict[str, Any]:
        client = self._ensure_client()
        args = MarketOrderArgsV2(
            token_id=token_id,
            amount=amount,
            side=side,
            order_type=OrderType.FAK,
        )
        resp = client.create_and_post_market_order(args, order_type=OrderType.FAK)
        log.info("market_order_posted", side=side, token_id=token_id, response=str(resp)[:200])
        if isinstance(resp, dict):
            return resp
        return {"raw": resp}

    def cancel_orders_for_token(self, token_id: str) -> None:
        client = self._ensure_client()
        try:
            from py_clob_client_v2.clob_types import OpenOrderParams

            orders = client.get_open_orders(OpenOrderParams(asset_id=token_id), only_first_page=True)
            for order in orders or []:
                oid = order.get("id") if isinstance(order, dict) else getattr(order, "id", None)
                if oid:
                    from py_clob_client_v2.clob_types import OrderPayload

                    client.cancel_order(OrderPayload(order_id=oid))
        except Exception as exc:
            log.warning("cancel_orders_failed", token_id=token_id, error=str(exc))
