"""Application configuration from YAML and environment."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


from politrade.paths import project_root as _project_root


def load_yaml_settings() -> dict[str, Any]:
    bundled = Path(__file__).resolve().parent / "config" / "settings.yaml"
    path = _project_root() / "config" / "settings.yaml"
    if not path.exists() and bundled.exists():
        path = bundled
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


_yaml = load_yaml_settings()


class EnvSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_project_root() / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    private_key: str = ""
    funder_address: str = ""
    signature_type: int = 0
    max_position_usd: float | None = None
    take_profit_multiplier: float | None = None
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    database_url: str = ""
    politrade_mode: str = "trade"
    dashboard_password: str = ""
    port: int = 8000


class AppConfig:
    """Merged configuration from YAML and environment."""

    def __init__(self) -> None:
        self.env = EnvSettings()
        self.yaml = _yaml

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
        if self.env.database_url:
            return self.env.database_url
        if os.environ.get("RENDER") or os.environ.get("RENDER_SERVICE_ID"):
            return "sqlite:////var/data/politrade.db"
        return "sqlite:///./data/politrade.db"

    @property
    def creds_path(self) -> Path:
        if os.environ.get("RENDER") or os.environ.get("RENDER_SERVICE_ID"):
            return Path("/var/data/creds.json")
        return Path.home() / ".politrade" / "creds.json"


def get_config() -> AppConfig:
    return AppConfig()
