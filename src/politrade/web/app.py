"""FastAPI dashboard — view and control the bot."""

from __future__ import annotations

import os
import secrets
from pathlib import Path

from fastapi import Depends, FastAPI, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from politrade.bot_runner import get_bot_runner
from politrade.config import get_config
from politrade.execution.risk import RiskManager
from politrade.storage.repository import Repository

WEB_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(WEB_DIR / "templates"))
security = HTTPBasic(auto_error=False)

app = FastAPI(title="Politrade Dashboard")
app.mount("/static", StaticFiles(directory=str(WEB_DIR / "static")), name="static")


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
    return {
        "config": config,
        "bot": runner.status,
        "kill_switch": risk.is_kill_switch_active(),
        "summary": summary,
        "open_positions": repo.get_open_positions(),
        "exposure": repo.total_open_exposure(),
        "leaders": repo.list_traders(active_only=True),
        "clob_configured": config.env.private_key and config.env.funder_address,
        "funder": config.env.funder_address or "—",
    }


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, _: None = Depends(_verify)) -> HTMLResponse:
    ctx = _dashboard_context()
    ctx["request"] = request
    return templates.TemplateResponse("dashboard.html", ctx)


@app.get("/leaders", response_class=HTMLResponse)
def leaders_page(request: Request, _: None = Depends(_verify)) -> HTMLResponse:
    repo = Repository()
    return templates.TemplateResponse(
        "leaders.html",
        {
            "request": request,
            "traders": repo.list_traders(active_only=False),
        },
    )


@app.get("/positions", response_class=HTMLResponse)
def positions_page(request: Request, _: None = Depends(_verify)) -> HTMLResponse:
    repo = Repository()
    return templates.TemplateResponse(
        "positions.html",
        {
            "request": request,
            "open_positions": repo.get_open_positions(),
            "closed_positions": repo.list_closed_positions(),
            "summary": repo.get_closed_positions_summary(),
        },
    )


@app.get("/logs", response_class=HTMLResponse)
def logs_page(request: Request, _: None = Depends(_verify)) -> HTMLResponse:
    repo = Repository()
    return templates.TemplateResponse(
        "logs.html",
        {"request": request, "logs": repo.list_audit_logs(80)},
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
    return {"ok": True, "bot": get_bot_runner().status}


def main() -> None:
    import uvicorn

    config = get_config()
    port = int(os.environ.get("PORT", config.env.port))
    uvicorn.run("politrade.web.app:app", host="0.0.0.0", port=port, reload=False)


if __name__ == "__main__":
    main()
