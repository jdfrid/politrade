"""Dashboard user settings persisted in SQLite."""

from __future__ import annotations

import json
from typing import Any

from politrade.config import AppConfig, get_config
from politrade.storage.repository import Repository

SETTINGS_KEY = "dashboard_settings"

DEFAULTS: dict[str, Any] = {
    "display_top_k": 5,
    "top_k": 5,
    "min_leader_profit_pct": 25,
    "min_leader_profit_pct_fallback": 10,
    "min_leader_score": 70,
    "opportunities_per_leader": 5,
    "scan_leaderboard_limit": 15,
    "min_win_rate": 0.50,
    "min_trades": 30,
}

LEADER_KEYS = frozenset(DEFAULTS.keys())


def load_user_settings(repo: Repository | None = None) -> dict[str, Any]:
    r = repo or Repository()
    raw = r.get_state(SETTINGS_KEY)
    if not raw:
        return dict(DEFAULTS)
    try:
        data = json.loads(raw)
        merged = dict(DEFAULTS)
        for key in LEADER_KEYS:
            if key in data and data[key] is not None:
                merged[key] = data[key]
        return merged
    except (json.JSONDecodeError, TypeError):
        return dict(DEFAULTS)


def save_user_settings(repo: Repository, data: dict[str, Any]) -> dict[str, Any]:
    merged = dict(DEFAULTS)
    for key in LEADER_KEYS:
        if key in data and data[key] is not None and data[key] != "":
            merged[key] = _coerce(key, data[key])
    repo.set_state(SETTINGS_KEY, json.dumps(merged))
    repo.audit("info", "settings_saved", json.dumps(merged, ensure_ascii=False))
    return merged


def _coerce(key: str, value: Any) -> Any:
    if key in ("min_win_rate",):
        return float(value)
    if key in ("min_leader_profit_pct", "min_leader_profit_pct_fallback"):
        return float(value)
    return int(value)


class EffectiveConfig:
    """AppConfig merged with dashboard user overrides."""

    def __init__(
        self,
        base: AppConfig | None = None,
        repo: Repository | None = None,
    ) -> None:
        self._base = base or get_config()
        self._repo = repo or Repository(self._base)
        self._user = load_user_settings(self._repo)

    @property
    def user_settings(self) -> dict[str, Any]:
        return dict(self._user)

    @property
    def leaders(self) -> dict[str, Any]:
        return {**self._base.leaders, **self._user}

    @property
    def copy(self) -> dict[str, Any]:
        copy_cfg = dict(self._base.copy)
        if "min_leader_score" in self._user:
            copy_cfg["min_leader_score"] = self._user["min_leader_score"]
        return copy_cfg

    @property
    def env(self):
        return self._base.env

    @property
    def risk(self):
        return self._base.risk

    @property
    def exit(self):
        return self._base.exit

    @property
    def api(self):
        return self._base.api

    @property
    def scoring(self):
        return self._base.scoring

    @property
    def yaml(self):
        return self._base.yaml

    @property
    def private_key(self) -> str:
        return self._base.private_key

    @property
    def funder_address(self) -> str:
        return self._base.funder_address

    @property
    def signature_type(self) -> int:
        return self._base.signature_type

    @property
    def database_url(self) -> str:
        return self._base.database_url

    @property
    def creds_path(self):
        return self._base.creds_path

    @property
    def kill_switch_path(self):
        return self._base.kill_switch_path

    @property
    def clob_configured(self) -> bool:
        return self._base.clob_configured

    def get(self, *keys: str, default: Any = None) -> Any:
        return self._base.get(*keys, default=default)


def get_effective_config() -> EffectiveConfig:
    return EffectiveConfig()
