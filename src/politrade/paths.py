"""Resolve project paths on local dev and Render."""

from __future__ import annotations

import os
from pathlib import Path


def project_root() -> Path:
    here = Path(__file__).resolve().parent
    for candidate in (here.parent.parent, here.parent, Path.cwd()):
        if (candidate / "config" / "settings.yaml").exists():
            return candidate
        if (candidate / "pyproject.toml").exists():
            return candidate
    return here.parent.parent


def web_dir() -> Path:
    return Path(__file__).resolve().parent / "web"


def resolve_sqlite_url(url: str) -> str:
    """Return SQLAlchemy URL with writable absolute path for SQLite."""
    if url.startswith("sqlite:///./"):
        rel = url.replace("sqlite:///./", "")
        db_path = project_root() / rel
    elif url.startswith("sqlite:////"):
        db_path = Path(url.replace("sqlite://", ""))
    elif url.startswith("sqlite:///"):
        raw = url[len("sqlite:///") :]
        db_path = Path(raw) if raw.startswith("/") else project_root() / raw
    else:
        return url

    try:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        test_file = db_path.parent / ".write_test"
        test_file.touch()
        test_file.unlink()
    except OSError:
        db_path = Path(os.environ.get("TMPDIR", "/tmp")) / "politrade" / "politrade.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)

    return f"sqlite:///{db_path.as_posix()}"
