"""FastAPI dashboard — view and control the bot."""

from __future__ import annotations

import logging
import os
import secrets
import traceback
from pathlib import Path

from fastapi import Depends, FastAPI, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from politrade.bot_runner import get_bot_runner
from politrade.config import get_config
from politrade.execution.risk import RiskManager
from politrade.paths import web_dir
from politrade.storage.repository import Repository

log = logging.getLogger(__name__)
WEB_DIR = web_dir()
TEMPLATES_DIR = WEB_DIR / "templates"
STATIC_DIR = WEB_DIR / "static"

if not TEMPLATES_DIR.is_dir():
    raise RuntimeError(f"Templates missing at {TEMPLATES_DIR}")

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
security = HTTPBasic(auto_error=False)

app = FastAPI(title="Politrade Dashboard")

if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.exception_handler(Exception)
async def unhandled_exception(request: Request, exc: Exception) -> JSONResponse:
    log.error("request_failed path=%s error=%s\n%s", request.url.path, exc, traceback.format_exc())
    return JSONResponse(
        status_code=500,
        content={"error": str(exc), "path": request.url.path},
    )


def _verify(credentials: HTTPBasicCredentials | None = Depends(security)) -> None:
    config = get_config()
    password = config.env.dashboard_password or os.environ.get("DASHBOARD_PASSWORD", "")
    if not password:
        return
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Basic"},
        )
    ok_user = secrets.compare_digest(credentials.username.encode(), b"admin")
    ok_pass = secrets.compare_digest(credentials.password.encode(), password.encode())
    if not (ok_user and ok_pass):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )


def _dashboard_context() -> dict:
    config = get_config()
    repo = Repository(config)
    runner = get_bot_runner()
    risk = RiskManager(config, repo)
    summary = repo.get_closed_positions_summary()
    funder = config.env.funder_address or "—"
    return {
        "config": config,
        "bot": runner.status,
        "kill_switch": risk.is_kill_switch_active(),
        "summary": summary,
        "open_positions": repo.get_open_positions(),
        "exposure": repo.total_open_exposure(),
        "leaders": repo.list_traders(active_only=True),
        "clob_configured": bool(config.env.private_key and config.env.funder_address),
        "funder": funder,
        "funder_short": (
            f"{funder[:10]}…{funder[-6:]}" if len(funder) > 16 else funder
        ),
    }


@app.on_event("startup")
def on_startup() -> None:
    try:
        Repository(get_config())
        log.info("database_ready templates=%s static=%s", TEMPLATES_DIR, STATIC_DIR)
    except Exception as exc:
        log.error("startup_db_failed: %s", exc)


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, _: None = Depends(_verify)) -> HTMLResponse:
    ctx = _dashboard_context()
    ctx["request"] = request
    return templates.TemplateResponse(request, "dashboard.html", ctx)


@app.get("/leaders", response_class=HTMLResponse)
def leaders_page(request: Request, _: None = Depends(_verify)) -> HTMLResponse:
    repo = Repository()
    return templates.TemplateResponse(
        request,
        "leaders.html",
        {"traders": repo.list_traders(active_only=False)},
    )


@app.get("/positions", response_class=HTMLResponse)
def positions_page(request: Request, _: None = Depends(_verify)) -> HTMLResponse:
    repo = Repository()
    return templates.TemplateResponse(
        request,
        "positions.html",
        {
            "open_positions": repo.get_open_positions(),
            "closed_positions": repo.list_closed_positions(),
            "summary": repo.get_closed_positions_summary(),
        },
    )


@app.get("/logs", response_class=HTMLResponse)
def logs_page(request: Request, _: None = Depends(_verify)) -> HTMLResponse:
    repo = Repository()
    return templates.TemplateResponse(
        request,
        "logs.html",
        {"logs": repo.list_audit_logs(80)},
    )


@app.post("/api/bot/start")
def api_bot_start(mode: str = Form("watch"), _: None = Depends(_verify)) -> RedirectResponse:
    if mode not in ("watch", "trade"):
        raise HTTPException(400, "mode must be watch or trade")
    get_bot_runner().start(mode)  # type: ignore[arg-type]
    return RedirectResponse(url="/", status_code=303)


@app.post("/api/bot/stop")
def api_bot_stop(_: None = Depends(_verify)) -> RedirectResponse:
    get_bot_runner().stop()
    return RedirectResponse(url="/", status_code=303)


@app.post("/api/scan")
def api_scan(_: None = Depends(_verify)) -> RedirectResponse:
    get_bot_runner().run_scan_once()
    return RedirectResponse(url="/leaders", status_code=303)


@app.post("/api/kill-switch")
def api_kill_switch(enable: str = Form("1"), _: None = Depends(_verify)) -> RedirectResponse:
    repo = Repository()
    if enable == "1":
        repo.set_state("kill_switch", "1")
    else:
        repo.set_state("kill_switch", "0")
    return RedirectResponse(url="/", status_code=303)


@app.get("/health")
def health() -> dict:
    db_ok = True
    try:
        Repository(get_config()).get_state("health_check")
    except Exception as exc:
        db_ok = False
        log.warning("health_db_failed: %s", exc)
    return {
        "ok": db_ok,
        "bot": get_bot_runner().status,
        "templates": str(TEMPLATES_DIR),
    }


def main() -> None:
    import uvicorn

    config = get_config()
    port = int(os.environ.get("PORT", config.env.port))
    uvicorn.run("politrade.web.app:app", host="0.0.0.0", port=port, reload=False)


if __name__ == "__main__":
    main()
