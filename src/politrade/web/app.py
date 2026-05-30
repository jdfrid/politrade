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

from politrade.analysis.trade_opportunities import (
    TradeOpportunity,
    _finalize_opportunities,
    _profit_thresholds,
    fetch_leader_opportunities_safe,
)
from politrade.bot_runner import get_bot_runner
from politrade.config import get_config
from politrade.config import get_config
from politrade.web.user_settings import get_effective_config, load_user_settings, save_user_settings
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
    config = get_effective_config()
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
def home(_: None = Depends(_verify)) -> RedirectResponse:
    return RedirectResponse(url="/settings", status_code=302)


@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, _: None = Depends(_verify)) -> HTMLResponse:
    config = get_effective_config()
    repo = Repository(config)
    return templates.TemplateResponse(
        request,
        "settings.html",
        {"settings": load_user_settings(repo)},
    )


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, _: None = Depends(_verify)) -> HTMLResponse:
    ctx = _dashboard_context()
    ctx["request"] = request
    return templates.TemplateResponse(request, "dashboard.html", ctx)


@app.get("/scan", response_class=HTMLResponse)
def scan_page(request: Request, _: None = Depends(_verify)) -> HTMLResponse:
    config = get_effective_config()
    repo = Repository(config)
    runner = get_bot_runner()
    settings = load_user_settings(repo)
    display_k = int(settings.get("display_top_k", 5))
    traders = repo.list_top_traders(limit=display_k)
    return templates.TemplateResponse(
        request,
        "scan.html",
        {
            "settings": settings,
            "scan_status": runner.scan_status(),
            "traders_preview": traders,
        },
    )


def _build_trades_page(request: Request, config) -> HTMLResponse:
    repo = Repository(config)
    settings = config.user_settings
    per_leader = int(settings.get("opportunities_per_leader", 5))
    display_k = int(settings.get("display_top_k", 5))
    max_refresh = int(config.leaders.get("max_leaders_refresh_per_load", 3))
    force_all = request.query_params.get("refresh") == "1"

    candidates = repo.list_top_traders(limit=display_k)

    leader_cards: list[dict] = []
    rate_warning: str | None = None
    refreshed = 0
    ttl = int(config.leaders.get("opportunity_cache_ttl_minutes", 20))
    min_profit_pct = float(settings.get("min_leader_profit_pct", 25))
    fallback_pct = float(settings.get("min_leader_profit_pct_fallback", 10))

    for t in candidates:
        should_fetch = force_all and refreshed < max_refresh
        err: str | None = None
        stale = False
        result = None

        if should_fetch:
            result, err, stale = fetch_leader_opportunities_safe(
                t.address,
                t.score,
                config=config,
                limit=per_leader,
                force_refresh=force_all,
            )
            opps = result.items
            refreshed += 1
        else:
            from politrade.analysis.opportunity_cache import get_cached

            cached = get_cached(t.address, ttl_minutes=ttl)
            if cached is not None:
                min_pct, min_usd, fb_pct = _profit_thresholds(config)
                result = _finalize_opportunities(
                    [TradeOpportunity(**d) for d in cached],
                    limit=per_leader,
                    min_pct=min_pct,
                    min_usd=min_usd,
                    fallback_pct=fb_pct,
                )
                opps = result.items
            else:
                opps = []
                err = "לא נטען — לחץ רענן למנהיג"

        if err and not rate_warning:
            rate_warning = err
        leader_cards.append(
            {
                "trader": t,
                "opportunities": opps,
                "scanned": result.scanned if result else 0,
                "relaxed_filter": result.relaxed if result else False,
                "used_min_pct": result.used_min_pct if result else min_profit_pct,
                "cache_stale": stale,
                "load_error": err,
            }
        )

    runner = get_bot_runner()
    dry_default = runner.mode == "watch" or not runner.is_running

    return templates.TemplateResponse(
        request,
        "trades.html",
        {
            "leader_cards": leader_cards,
            "dry_default": dry_default,
            "clob_configured": config.clob_configured,
            "rate_warning": rate_warning,
            "min_profit_pct": min_profit_pct,
            "fallback_pct": fallback_pct,
            "display_k": display_k,
        },
    )


@app.get("/trades", response_class=HTMLResponse)
def trades_page(request: Request, _: None = Depends(_verify)) -> HTMLResponse:
    return _build_trades_page(request, get_effective_config())


@app.get("/leaders", response_class=HTMLResponse)
def leaders_redirect(_: None = Depends(_verify)) -> RedirectResponse:
    return RedirectResponse(url="/trades", status_code=301)


@app.post("/api/refresh-leader/{address}")
def api_refresh_leader(address: str, _: None = Depends(_verify)) -> RedirectResponse:
    config = get_effective_config()
    repo = Repository(config)
    with repo.session() as s:
        trader = s.get(Trader, address.lower())
    score = trader.score if trader else 0.0
    per_leader = int(config.user_settings.get("opportunities_per_leader", 5))
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
    return RedirectResponse(url="/trades", status_code=303)


@app.post("/api/settings")
def api_settings(
    display_top_k: int = Form(...),
    top_k: int = Form(...),
    scan_leaderboard_limit: int = Form(...),
    min_leader_score: int = Form(...),
    min_win_rate: float = Form(...),
    min_trades: int = Form(...),
    min_leader_profit_pct: float = Form(...),
    min_leader_profit_pct_fallback: float = Form(...),
    opportunities_per_leader: int = Form(...),
    _: None = Depends(_verify),
) -> RedirectResponse:
    config = get_effective_config()
    repo = Repository(config)
    save_user_settings(
        repo,
        {
            "display_top_k": display_top_k,
            "top_k": top_k,
            "scan_leaderboard_limit": scan_leaderboard_limit,
            "min_leader_score": min_leader_score,
            "min_win_rate": min_win_rate,
            "min_trades": min_trades,
            "min_leader_profit_pct": min_leader_profit_pct,
            "min_leader_profit_pct_fallback": min_leader_profit_pct_fallback,
            "opportunities_per_leader": opportunities_per_leader,
        },
    )
    return RedirectResponse(url="/scan", status_code=303)


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
    config = get_effective_config()
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
        return RedirectResponse(url="/trades?err=invalid", status_code=303)

    is_dry = dry_run == "1"
    ok, msg = executor.execute_manual(signal, dry_run=is_dry)
    repo.audit("info" if ok else "error", "manual_copy", f"{trade_id} {msg}")
    param = "copied" if ok else "failed"
    return RedirectResponse(url=f"/trades?{param}=1", status_code=303)


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
    return RedirectResponse(url="/dashboard", status_code=303)


@app.post("/api/bot/stop")
def api_bot_stop(_: None = Depends(_verify)) -> RedirectResponse:
    get_bot_runner().stop()
    return RedirectResponse(url="/dashboard", status_code=303)


@app.post("/api/scan")
def api_scan(_: None = Depends(_verify)) -> RedirectResponse:
    runner = get_bot_runner()
    if not runner.start_scan_async():
        return RedirectResponse(url="/scan?scan_running=1", status_code=303)
    return RedirectResponse(url="/scan?scanning=1", status_code=303)


@app.get("/api/scan-status")
def api_scan_status(_: None = Depends(_verify)) -> dict:
    return get_bot_runner().scan_status()


@app.post("/api/kill-switch")
def api_kill_switch(enable: str = Form("1"), _: None = Depends(_verify)) -> RedirectResponse:
    repo = Repository()
    if enable == "1":
        repo.set_state("kill_switch", "1")
    else:
        repo.set_state("kill_switch", "0")
    return RedirectResponse(url="/dashboard", status_code=303)


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
