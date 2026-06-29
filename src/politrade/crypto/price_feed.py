"""Chainlink oracle price feed for crypto windows."""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from politrade.crypto.window import CryptoAsset, CryptoWindow, WINDOW_SECONDS
from politrade.logging_setup import get_logger

log = get_logger(__name__)

WS_URL = "wss://ws-live-data.polymarket.com"
HTTP_FALLBACK_URL = "https://polymarket.com/api/crypto/crypto-price"


@dataclass
class OracleSnapshot:
    asset: CryptoAsset
    window_ts: int
    open_price: float | None = None
    current_price: float | None = None
    close_price: float | None = None
    price_history: list[tuple[int, float]] = field(default_factory=list)

    @property
    def delta_pct(self) -> float | None:
        if self.open_price is None or self.current_price is None or self.open_price <= 0:
            return None
        return ((self.current_price - self.open_price) / self.open_price) * 100

    @property
    def direction(self) -> str:
        d = self.delta_pct
        if d is None:
            return "flat"
        if d > 0:
            return "up"
        if d < 0:
            return "down"
        return "flat"

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset": self.asset.value,
            "window_ts": self.window_ts,
            "open_price": self.open_price,
            "current_price": self.current_price,
            "close_price": self.close_price,
            "delta_pct": round(self.delta_pct, 4) if self.delta_pct is not None else None,
            "direction": self.direction,
            "history": [{"ts": ts, "price": p} for ts, p in self.price_history[-60:]],
        }


@dataclass
class TokenPrices:
    up_mid: float | None = None
    up_ask: float | None = None
    up_bid: float | None = None
    down_mid: float | None = None
    down_ask: float | None = None
    down_bid: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "up_mid": self.up_mid,
            "up_ask": self.up_ask,
            "up_bid": self.up_bid,
            "down_mid": self.down_mid,
            "down_ask": self.down_ask,
            "down_bid": self.down_bid,
        }


def edge_pct_from_ask(ask: float | None) -> float | None:
    if ask is None or ask <= 0 or ask >= 1:
        return None
    return ((1.0 - ask) / ask) * 100


class ChainlinkPriceFeed:
    """Singleton feed — WebSocket with HTTP polling fallback."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._prices: dict[str, float] = {}
        self._windows: dict[str, OracleSnapshot] = {}
        self._ws_running = False
        self._ws_thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._last_ws_error: str | None = None
        self._http = httpx.Client(timeout=10)

    @property
    def last_ws_error(self) -> str | None:
        return self._last_ws_error

    def start(self) -> None:
        if self._ws_thread and self._ws_thread.is_alive():
            return
        self._stop.clear()
        self._ws_thread = threading.Thread(target=self._ws_loop, name="chainlink-ws", daemon=True)
        self._ws_thread.start()
        log.info("chainlink_feed_started")

    def stop(self) -> None:
        self._stop.set()
        if self._ws_thread:
            self._ws_thread.join(timeout=5)
        self._http.close()

    def _ws_loop(self) -> None:
        while not self._stop.is_set():
            try:
                import websockets.sync.client as ws_client

                with ws_client.connect(WS_URL, open_timeout=10) as ws:
                    self._ws_running = True
                    self._last_ws_error = None
                    sub = {
                        "action": "subscribe",
                        "subscriptions": [
                            {
                                "topic": "crypto_prices_chainlink",
                                "type": "update",
                            }
                        ],
                    }
                    ws.send(json.dumps(sub))
                    while not self._stop.is_set():
                        try:
                            raw = ws.recv(timeout=5)
                        except TimeoutError:
                            continue
                        self._handle_ws_message(raw)
            except Exception as exc:
                self._ws_running = False
                self._last_ws_error = str(exc)
                log.warning("chainlink_ws_error", error=str(exc))
                self._stop.wait(5)

    def _handle_ws_message(self, raw: str | bytes) -> None:
        try:
            msg = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
        except (json.JSONDecodeError, TypeError):
            return
        if not isinstance(msg, dict):
            return
        payload = msg.get("payload") or msg.get("data") or msg
        if not isinstance(payload, dict):
            return
        symbol = str(payload.get("symbol") or payload.get("pair") or "").lower()
        price_raw = payload.get("value") or payload.get("price")
        if not symbol or price_raw is None:
            topic = str(msg.get("topic") or "")
            if "chainlink" in topic.lower():
                symbol = str(payload.get("symbol") or "btc/usd").lower()
                price_raw = payload.get("value") or payload.get("price")
        if not symbol or price_raw is None:
            return
        try:
            price = float(price_raw)
        except (TypeError, ValueError):
            return
        with self._lock:
            self._prices[symbol] = price
            self._update_window_snapshots(symbol, price)

    def _update_window_snapshots(self, symbol: str, price: float) -> None:
        now = int(time.time())
        window_ts = (now // WINDOW_SECONDS) * WINDOW_SECONDS
        for asset in CryptoAsset:
            if asset.chainlink_pair != symbol:
                continue
            key = _snap_key(asset, window_ts)
            snap = self._windows.get(key)
            if snap is None:
                snap = OracleSnapshot(asset=asset, window_ts=window_ts, open_price=price, current_price=price)
                self._windows[key] = snap
            else:
                if snap.open_price is None and now >= window_ts:
                    snap.open_price = price
                snap.current_price = price
            snap.price_history.append((now, price))
            if len(snap.price_history) > 300:
                snap.price_history = snap.price_history[-300:]

    def poll_http_fallback(self) -> None:
        """Poll Polymarket crypto price HTTP as fallback."""
        for asset in CryptoAsset:
            try:
                resp = self._http.get(
                    HTTP_FALLBACK_URL,
                    params={"symbol": asset.value.upper()},
                )
                if resp.status_code != 200:
                    continue
                data = resp.json()
                price = float(data.get("price") or data.get("value") or 0)
                if price > 0:
                    with self._lock:
                        self._prices[asset.chainlink_pair] = price
                        self._update_window_snapshots(asset.chainlink_pair, price)
            except Exception as exc:
                log.debug("http_price_fallback_failed", asset=asset.value, error=str(exc))

    def get_price(self, asset: CryptoAsset) -> float | None:
        with self._lock:
            return self._prices.get(asset.chainlink_pair)

    def get_snapshot(self, window: CryptoWindow) -> OracleSnapshot:
        key = _snap_key(window.asset, window.window_ts)
        with self._lock:
            snap = self._windows.get(key)
            if snap is None:
                price = self._prices.get(window.asset.chainlink_pair)
                snap = OracleSnapshot(
                    asset=window.asset,
                    window_ts=window.window_ts,
                    open_price=price,
                    current_price=price,
                )
                self._windows[key] = snap
            return snap

    def set_close_price(self, asset: CryptoAsset, window_ts: int, price: float) -> None:
        key = _snap_key(asset, window_ts)
        with self._lock:
            snap = self._windows.get(key)
            if snap is None:
                snap = OracleSnapshot(asset=asset, window_ts=window_ts)
                self._windows[key] = snap
            snap.close_price = price
            snap.current_price = price

    def status(self) -> dict[str, Any]:
        with self._lock:
            symbols = list(self._prices.keys())
        return {
            "ws_running": self._ws_running,
            "last_ws_error": self._last_ws_error,
            "symbols": symbols,
        }


def _snap_key(asset: CryptoAsset, window_ts: int) -> str:
    return f"{asset.value}:{window_ts}"


def fetch_token_prices(clob: Any, window: CryptoWindow) -> TokenPrices:
    """Fetch Up/Down token prices from CLOB."""
    prices = TokenPrices()
    if not clob.is_configured:
        return prices
    try:
        prices.up_mid = clob.get_mid_price(window.up_token_id)
        prices.down_mid = clob.get_mid_price(window.down_token_id)
        book_up = _top_of_book(clob, window.up_token_id)
        book_down = _top_of_book(clob, window.down_token_id)
        if book_up:
            prices.up_bid, prices.up_ask = book_up
        if book_down:
            prices.down_bid, prices.down_ask = book_down
    except Exception as exc:
        log.warning("fetch_token_prices_failed", slug=window.slug, error=str(exc))
    return prices


def _top_of_book(clob: Any, token_id: str) -> tuple[float, float] | None:
    client = clob._ensure_client()
    try:
        book = client.get_order_book(token_id)
        bids = book.get("bids", []) if isinstance(book, dict) else (book.bids or [])
        asks = book.get("asks", []) if isinstance(book, dict) else (book.asks or [])
        if not bids or not asks:
            return None
        bid = float(bids[0]["price"] if isinstance(bids[0], dict) else bids[0].price)
        ask = float(asks[0]["price"] if isinstance(asks[0], dict) else asks[0].price)
        return bid, ask
    except Exception:
        return None


_feed: ChainlinkPriceFeed | None = None


def get_price_feed() -> ChainlinkPriceFeed:
    global _feed
    if _feed is None:
        _feed = ChainlinkPriceFeed()
    return _feed
