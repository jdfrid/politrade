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


def normalize_eth_address(raw: str) -> tuple[str | None, str | None]:
    """Return (address, error_he) — adds 0x prefix if missing."""
    s = (raw or "").strip()
    if not s:
        return None, "חסרה כתובת Funder / Deposit"
    if not s.lower().startswith("0x"):
        s = "0x" + s
    if len(s) != 42:
        return None, (
            f"כתובת לא מלאה ({len(s) - 2} תווים במקום 40). "
            "העתק את כל ה-Deposit Address מ-Polymarket (כולל 0x)."
        )
    try:
        int(s[2:], 16)
    except ValueError:
        return None, "כתובת לא תקינה — רק ספרות ואותיות a-f"
    return s, None


def normalize_private_key(raw: str | None, *, required: bool = True) -> tuple[str | None, str | None]:
    s = (raw or "").strip()
    if not s:
        if required:
            return None, "חסר Private Key"
        return None, None
    if not s.startswith("0x"):
        s = "0x" + s
    if len(s) < 66:
        return None, "Private Key קצר מדי — ודא שהעתקת את כל המפתח"
    return s, None


def wallet_validation_errors(config: AppConfig | None = None) -> list[str]:
    cfg = config or get_config()
    errors: list[str] = []
    pk = cfg.private_key
    funder = cfg.funder_address
    if not pk:
        errors.append("חסר Private Key — הזן מפתח או שמור קיים מהפעם הקודמת")
    elif not pk.startswith("0x") or len(pk) < 66:
        errors.append("Private Key לא תקין")
    if not funder:
        errors.append("חסר Funder / Deposit Address")
    elif not funder.startswith("0x") or len(funder) != 42:
        errors.append(
            f"כתובת Funder לא מלאה ({len(funder) - 2 if funder.startswith('0x') else len(funder)} "
            "תווים במקום 40) — דוגמה: 0x088549349ff6deB90e60697012672A66743B1FFF"
        )
    return errors


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

    funder_norm, funder_err = normalize_eth_address(funder_address)
    if funder_err:
        raise ValueError(funder_err)
    if not pk:
        raise ValueError("חסר Private Key — הזן מפתח או השאר ריק רק אם כבר שמרת בעבר")
    pk_norm, pk_err = normalize_private_key(pk, required=True)
    if pk_err:
        raise ValueError(pk_err)
    pk = pk_norm or pk

    payload = {
        "private_key": pk,
        "funder_address": funder_norm,
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
        "errors": wallet_validation_errors(cfg),
    }
