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

from politrade.analysis.opportunity_cache import get_cached
from politrade.analysis.trade_opportunities import fetch_leader_opportunities_safe
from politrade.bot_runner import get_bot_runner
from politrade.config import get_config
from politrade.execution.order_executor import OrderExecutor
from politrade.execution.risk import RiskManager
from politrade.paths import web_dir
from politrade.signals.trade_selector import TradeSelector
from politrade.storage.models import Trader
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
    funder = config.funder_address or "—"
    return {
        "config": config,
        "bot": runner.status,
        "kill_switch": risk.is_kill_switch_active(),
        "summary": summary,
        "open_positions": repo.get_open_positions(),
        "exposure": repo.total_open_exposure(),
        "leaders": repo.list_traders(active_only=True),
        "clob_configured": config.clob_configured,
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
    config = get_config()
    repo = Repository(config)
    per_leader = int(config.leaders.get("opportunities_per_leader", 5))
    show_all = bool(config.leaders.get("show_opportunities_for_all", False))
    max_refresh = int(config.leaders.get("max_leaders_refresh_per_load", 3))
    force_all = request.query_params.get("refresh") == "1"

    candidates = repo.list_traders(active_only=not show_all)

    leader_cards: list[dict] = []
    rate_warning: str | None = None
    refreshed = 0
    ttl = int(config.leaders.get("opportunity_cache_ttl_minutes", 20))

    for t in candidates:
        should_fetch = force_all or (t.is_active_leader and refreshed < max_refresh)
        err: str | None = None
        stale = False

        if should_fetch:
            opps, err, stale = fetch_leader_opportunities_safe(
                t.address,
                t.score,
                config=config,
                limit=per_leader,
                force_refresh=force_all,
            )
            refreshed += 1
        else:
            cached = get_cached(t.address, ttl_minutes=ttl)
            if cached is not None:
                from politrade.analysis.trade_opportunities import TradeOpportunity

                opps = [TradeOpportunity(**d) for d in cached]
            else:
                opps = []
                err = "לא נטען — לחץ רענן למנהיג זה"

        if err and not rate_warning:
            rate_warning = err
        leader_cards.append(
            {
                "trader": t,
                "opportunities": opps,
                "cache_stale": stale,
                "load_error": err,
            }
        )

    runner = get_bot_runner()
    dry_default = runner.mode == "watch" or not runner.is_running

    min_profit_pct = float(config.leaders.get("min_leader_profit_pct", 40))

    return templates.TemplateResponse(
        request,
        "leaders.html",
        {
            "leader_cards": leader_cards,
            "dry_default": dry_default,
            "clob_configured": config.clob_configured,
            "rate_warning": rate_warning,
            "min_profit_pct": min_profit_pct,
        },
    )


@app.post("/api/refresh-leader/{address}")
def api_refresh_leader(address: str, _: None = Depends(_verify)) -> RedirectResponse:
    config = get_config()
    repo = Repository(config)
    with repo.session() as s:
        trader = s.get(Trader, address.lower())
    score = trader.score if trader else 0.0
    per_leader = int(config.leaders.get("opportunities_per_leader", 5))
    try:
        fetch_leader_opportunities_safe(
            address,
            score,
            config=config,
            limit=per_leader,
            force_refresh=True,
        )
    except Exception as exc:
        repo.audit("error", "refresh_leader_failed", str(exc))
    return RedirectResponse(url="/leaders", status_code=303)


@app.post("/api/copy-trade")
def api_copy_trade(
    request: Request,
    leader_address: str = Form(...),
    trade_id: str = Form(...),
    token_id: str = Form(...),
    market_id: str = Form(...),
    price: float = Form(0),
    size_usd: float = Form(0),
    dry_run: str = Form("0"),
    _: None = Depends(_verify),
) -> RedirectResponse:
    config = get_config()
    repo = Repository(config)
    selector = TradeSelector(config, repo)
    executor = OrderExecutor(config, repo)

    trade = {
        "id": trade_id,
        "asset": token_id,
        "conditionId": market_id,
        "side": "BUY",
        "price": price,
        "usdcSize": size_usd,
        "proxyWallet": leader_address,
    }
    signal = selector.build_signal(trade, leader_address)
    if signal is None:
        repo.audit("error", "manual_copy_invalid", trade_id)
        return RedirectResponse(url="/leaders?err=invalid", status_code=303)

    is_dry = dry_run == "1"
    ok, msg = executor.execute_manual(signal, dry_run=is_dry)
    repo.audit("info" if ok else "error", "manual_copy", f"{trade_id} {msg}")
    param = "copied" if ok else "failed"
    return RedirectResponse(url=f"/leaders?{param}=1", status_code=303)


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
    cfg = get_config()
    return {
        "ok": db_ok,
        "bot": get_bot_runner().status,
        "clob_configured": cfg.clob_configured,
        "has_private_key": bool(cfg.private_key),
        "has_funder": bool(cfg.funder_address),
    }


def main() -> None:
    import uvicorn

    config = get_config()
    port = int(os.environ.get("PORT", config.env.port))
    uvicorn.run("politrade.web.app:app", host="0.0.0.0", port=port, reload=False)


if __name__ == "__main__":
    main()
