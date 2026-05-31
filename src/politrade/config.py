"""Application configuration from YAML and environment."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from politrade.paths import project_root as _project_root


def _env_file_for_settings() -> str | None:
    """Skip .env on Render — use platform env vars only."""
    if os.environ.get("RENDER") or os.environ.get("RENDER_SERVICE_ID"):
        return None
    path = _project_root() / ".env"
    return str(path) if path.exists() else None


def load_yaml_settings() -> dict[str, Any]:
    bundled = Path(__file__).resolve().parent / "bundled" / "settings.yaml"
    path = _project_root() / "config" / "settings.yaml"
    if not path.exists() and bundled.exists():
        path = bundled
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


_yaml = load_yaml_settings()


def _read_env(name: str, fallback: str = "") -> str:
    return (os.environ.get(name) or fallback or "").strip()


def wallet_json_path() -> Path:
    if os.environ.get("RENDER") or os.environ.get("RENDER_SERVICE_ID"):
        return Path("/var/data/wallet.json")
    return Path.home() / ".politrade" / "wallet.json"


def _load_wallet_secrets() -> dict[str, Any]:
    path = wallet_json_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


class EnvSettings(BaseSettings):
    """Load secrets from environment (Render) or local .env."""

    model_config = SettingsConfigDict(
        env_file=_env_file_for_settings(),
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    # `private_key` is reserved/problematic in Pydantic — use explicit aliases
    wallet_private_key: str = Field(default="", validation_alias="PRIVATE_KEY")
    wallet_funder: str = Field(default="", validation_alias="FUNDER_ADDRESS")
    signature_type: int = Field(default=0, validation_alias="SIGNATURE_TYPE")
    max_position_usd: float | None = Field(default=None, validation_alias="MAX_POSITION_USD")
    take_profit_multiplier: float | None = Field(
        default=None, validation_alias="TAKE_PROFIT_MULTIPLIER"
    )
    telegram_bot_token: str = Field(default="", validation_alias="TELEGRAM_BOT_TOKEN")
    telegram_chat_id: str = Field(default="", validation_alias="TELEGRAM_CHAT_ID")
    database_url: str = Field(default="", validation_alias="DATABASE_URL")
    politrade_mode: str = Field(default="trade", validation_alias="POLITRADE_MODE")
    dashboard_password: str = Field(default="", validation_alias="DASHBOARD_PASSWORD")
    port: int = Field(default=8000, validation_alias="PORT")


class AppConfig:
    """Merged configuration from YAML and environment."""

    def __init__(self) -> None:
        self.env = EnvSettings()
        self.yaml = _yaml

    @property
    def private_key(self) -> str:
        env_val = _read_env("PRIVATE_KEY", self.env.wallet_private_key)
        if env_val:
            return env_val
        return str(_load_wallet_secrets().get("private_key", "") or "").strip()

    @property
    def funder_address(self) -> str:
        env_val = _read_env("FUNDER_ADDRESS", self.env.wallet_funder)
        if env_val:
            return env_val
        return str(_load_wallet_secrets().get("funder_address", "") or "").strip()

    @property
    def signature_type(self) -> int:
        raw = os.environ.get("SIGNATURE_TYPE")
        if raw is not None and raw != "":
            return int(raw)
        wallet = _load_wallet_secrets()
        if wallet.get("signature_type") is not None:
            return int(wallet["signature_type"])
        return self.env.signature_type

    def get(self, *keys: str, default: Any = None) -> Any:
        node: Any = self.yaml
        for key in keys:
            if not isinstance(node, dict):
                return default
            node = node.get(key)
            if node is None:
                return default
        return node

    @property
    def leaders(self) -> dict[str, Any]:
        return self.get("leaders", default={})

    @property
    def copy(self) -> dict[str, Any]:
        return self.get("copy", default={})

    @property
    def risk(self) -> dict[str, Any]:
        risk = dict(self.get("risk", default={}))
        if self.env.max_position_usd is not None:
            risk["max_position_usd"] = self.env.max_position_usd
        return risk

    @property
    def exit(self) -> dict[str, Any]:
        exit_cfg = dict(self.get("exit", default={}))
        if self.env.take_profit_multiplier is not None:
            exit_cfg["take_profit_multiplier"] = self.env.take_profit_multiplier
        return exit_cfg

    @property
    def api(self) -> dict[str, Any]:
        return self.get("api", default={})

    @property
    def scoring(self) -> dict[str, Any]:
        return self.get("scoring", default={})

    @property
    def kill_switch_path(self) -> Path:
        return _project_root() / "STOP_TRADING"

    @property
    def database_url(self) -> str:
        url = _read_env("DATABASE_URL", self.env.database_url)
        if url:
            return url
        if os.environ.get("RENDER") or os.environ.get("RENDER_SERVICE_ID"):
            return "sqlite:////var/data/politrade.db"
        return "sqlite:///./data/politrade.db"

    @property
    def creds_path(self) -> Path:
        if os.environ.get("RENDER") or os.environ.get("RENDER_SERVICE_ID"):
            return Path("/var/data/creds.json")
        return Path.home() / ".politrade" / "creds.json"

    @property
    def clob_configured(self) -> bool:
        pk = self.private_key
        fd = self.funder_address
        return (
            bool(pk)
            and bool(fd)
            and pk.startswith("0x")
            and len(pk) >= 66
            and fd.startswith("0x")
            and len(fd) >= 42
        )


def get_config() -> AppConfig:
    return AppConfig()
