"""Optional Telegram notifications."""

from __future__ import annotations

import httpx

from politrade.config import AppConfig
from politrade.logging_setup import get_logger

log = get_logger(__name__)


class Notifier:
    def __init__(self, config: AppConfig | None = None) -> None:
        self.config = config or AppConfig()

    @property
    def enabled(self) -> bool:
        env = self.config.env
        return bool(env.telegram_bot_token and env.telegram_chat_id)

    def send(self, message: str) -> None:
        if not self.enabled:
            log.info("notification", message=message)
            return
        env = self.config.env
        url = f"https://api.telegram.org/bot{env.telegram_bot_token}/sendMessage"
        try:
            httpx.post(
                url,
                json={"chat_id": env.telegram_chat_id, "text": message[:4000]},
                timeout=10,
            )
        except Exception as exc:
            log.warning("telegram_send_failed", error=str(exc))
