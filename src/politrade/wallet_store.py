"""Persist wallet credentials for CLOB trading (Render disk or local)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from politrade.api.clob_client import ClobClientWrapper
from politrade.config import AppConfig, get_config, wallet_json_path
from politrade.storage.repository import Repository


def wallet_path(config: AppConfig | None = None) -> Path:
    return wallet_json_path()


def load_wallet(config: AppConfig | None = None) -> dict[str, Any]:
    path = wallet_path(config)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_wallet(
    *,
    private_key: str | None,
    funder_address: str,
    signature_type: int = 1,
    config: AppConfig | None = None,
    repo: Repository | None = None,
) -> None:
    cfg = config or get_config()
    path = wallet_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)

    existing = load_wallet(cfg)
    pk = (private_key or "").strip()
    if not pk:
        pk = existing.get("private_key", "")

    payload = {
        "private_key": pk,
        "funder_address": funder_address.strip(),
        "signature_type": int(signature_type),
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass

    r = repo or Repository(cfg)
    r.audit("info", "wallet_saved", f"funder={payload['funder_address'][:10]}…")
    reset_clob_creds(cfg)


def reset_clob_creds(config: AppConfig | None = None) -> None:
    ClobClientWrapper(config or get_config()).reset_stored_creds()


def wallet_status(config: AppConfig | None = None) -> dict[str, Any]:
    cfg = config or get_config()
    stored = load_wallet(cfg)
    pk = cfg.private_key
    funder = cfg.funder_address
    return {
        "configured": cfg.clob_configured,
        "funder_address": funder,
        "funder_short": (
            f"{funder[:10]}…{funder[-6:]}" if len(funder) > 16 else funder
        ),
        "signature_type": cfg.signature_type,
        "has_stored_key": bool(stored.get("private_key")),
        "source_env": bool(os.environ.get("PRIVATE_KEY") and os.environ.get("FUNDER_ADDRESS")),
    }
