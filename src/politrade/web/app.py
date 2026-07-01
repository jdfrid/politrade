"""FastAPI dashboard — view and control the bot."""

from __future__ import annotations

import logging
import os
import secrets
import traceback
from pathlib import Path

from urllib.parse import quote

from fastapi import Depends, FastAPI, Form, HTTPException, Request, status
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from politrade.crypto.executor import CryptoBetExecutor
from politrade.crypto.live_state import build_crypto_live, invalidate_wallet_cache
from politrade.crypto.sim_live_state import build_sim_cycles, build_sim_live
from politrade.crypto.sim_mode import (
    MODE_LIVE,
    MODE_SIMULATION,
    can_enable_live,
    is_live_enabled,
    set_auto_learn,
    set_trading_mode,
)
from politrade.crypto.runner import get_crypto_runner
from politrade.crypto.sim_display import enrich_sim_bet_dict
from politrade.crypto.sim_runner import get_sim_runner
from politrade.crypto.price_feed import edge_pct_from_ask, fetch_token_prices, get_price_feed
from politrade.crypto.window import CryptoAsset, fetch_window_market, compute_window_ts
from politrade.analysis.trade_opportunities import fetch_leader_opportunities_safe
from politrade.analysis.hot_markets import fetch_hot_market_opportunities
from politrade.bot_runner import get_bot_runner
from politrade.config import get_config
from politrade.web.user_settings import get_effective_config, load_user_settings, save_user_settings
from politrade.execution.order_executor import OrderExecutor
from politrade.execution.risk import RiskManager
from politrade.paths import project_root, web_dir
from politrade.signals.trade_selector import TradeSelector
from politrade.storage.models import Trader
from politrade.storage.repository import Repository
from politrade.execution.position_monitor import get_position_monitor
from politrade.web.live_positions import build_live_positions_summary
from politrade.web.system_status import build_live_status
from politrade.web.wallet_activity import build_wallet_activity, wallet_activity_to_dict
from politrade.web.portfolio_trade import (
    execute_portfolio_buy,
    execute_portfolio_sell,
    fetch_market_preview,
)
from politrade.wallet_store import save_wallet, wallet_status, reset_clob_creds

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
    live = build_live_positions_summary(config, repo)
    return {
        "config": config,
        "bot": runner.status,
        "kill_switch": risk.is_kill_switch_active(),
        "summary": summary,
        "open_positions": repo.get_open_positions(),
        "live_positions": live,
        "exposure": repo.total_open_exposure(),
        "leaders": repo.list_traders(active_only=True),
        "clob_configured": config.clob_configured,
        "funder": funder,
        "funder_short": (
            f"{funder[:10]}…{funder[-6:]}" if len(funder) > 16 else funder
        ),
        "position_monitor": get_position_monitor().status,
    }


@app.on_event("startup")
def on_startup() -> None:
    try:
        Repository(get_config())
        log.info("database_ready templates=%s static=%s", TEMPLATES_DIR, STATIC_DIR)
        get_price_feed().start()
        runner = get_sim_runner()
        runner.start()
        repo = Repository(get_config())
        if repo.get_state("sim_auto_run") is None:
            runner.set_auto_sim(True)
        if is_live_enabled(Repository(get_config())):
            get_crypto_runner().start()
            log.info("crypto_runner_live_enabled")
        log.info("sim_runner_ready")
    except Exception as exc:
        log.error("startup_db_failed: %s", exc)


@app.get("/", response_class=HTMLResponse)
def home(_: None = Depends(_verify)) -> RedirectResponse:
    return RedirectResponse(url="/sim", status_code=302)


@app.get("/sim", response_class=HTMLResponse)
def sim_page(request: Request, _: None = Depends(_verify)) -> HTMLResponse:
    return templates.TemplateResponse(request, "simulation.html", {})


@app.get("/api/sim/live")
def api_sim_live(_: None = Depends(_verify)) -> dict:
    return build_sim_live(get_effective_config())


@app.get("/api/sim/cycles")
def api_sim_cycles(_: None = Depends(_verify)) -> dict:
    return build_sim_cycles(get_effective_config())


@app.post("/api/sim/start")
def api_sim_start(_: None = Depends(_verify)) -> dict:
    runner = get_sim_runner()
    if not runner.is_running:
        runner.start()
    runner.set_auto_sim(True)
    return {"ok": True, "running": True}


@app.post("/api/sim/stop")
def api_sim_stop(_: None = Depends(_verify)) -> dict:
    get_sim_runner().set_auto_sim(False)
    return {"ok": True, "auto_sim": False}


@app.post("/api/sim/reset")
def api_sim_reset(
    start_balance: float = Form(1000),
    _: None = Depends(_verify),
) -> RedirectResponse:
    repo = Repository(get_effective_config())
    repo.reset_sim_ledger(start_balance)
    from politrade.crypto.sim_optimizer import ensure_population

    ensure_population(repo, start_balance)
    repo.audit("info", "sim_reset", f"balance={start_balance}")
    return RedirectResponse(url="/sim?reset=1", status_code=303)


@app.post("/api/sim/enable-live")
def api_sim_enable_live(_: None = Depends(_verify)) -> RedirectResponse:
    repo = Repository(get_effective_config())
    ok, reason = can_enable_live(repo)
    if not ok:
        return RedirectResponse(url=f"/settings?live_err={quote(reason)}", status_code=303)
    set_trading_mode(repo, MODE_LIVE)
    get_crypto_runner().start()
    return RedirectResponse(url="/settings?live=1", status_code=303)


@app.post("/api/sim/disable-live")
def api_sim_disable_live(_: None = Depends(_verify)) -> RedirectResponse:
    repo = Repository(get_effective_config())
    set_trading_mode(repo, MODE_SIMULATION)
    return RedirectResponse(url="/settings?sim=1", status_code=303)


@app.get("/crypto", response_class=HTMLResponse)
def crypto_page(_: None = Depends(_verify)) -> RedirectResponse:
    return RedirectResponse(url="/sim", status_code=302)


@app.get("/api/crypto/live")
def api_crypto_live(_: None = Depends(_verify)) -> dict:
    return build_crypto_live(get_effective_config())


@app.post("/api/crypto/auto")
def api_crypto_auto(enabled: str = Form("1"), _: None = Depends(_verify)) -> dict:
    get_crypto_runner().set_auto_bet(enabled == "1")
    return {"auto_bet": enabled == "1"}


@app.get("/api/crypto/markets")
def api_crypto_markets(_: None = Depends(_verify)) -> dict:
    from politrade.crypto.live_state import _cached_markets_catalog

    config = get_effective_config()
    repo = Repository(config)
    try:
        return _cached_markets_catalog(config, repo)
    except Exception as exc:
        log.warning("markets_catalog_failed", error=str(exc))
        return {
            "updated_at": 0,
            "trading_ready": False,
            "markets": [],
            "open_count": 0,
            "buyable_count": 0,
            "error": str(exc)[:120],
        }


@app.post("/api/crypto/bet")
def api_crypto_bet(
    asset: str = Form(...),
    side: str = Form(...),
    amount: float = Form(5),
    window_ts: int = Form(0),
    _: None = Depends(_verify),
) -> dict:
    config = get_effective_config()
    repo = Repository(config)
    if not is_live_enabled(repo):
        raise HTTPException(
            status_code=403,
            detail="מסחר אמיתי נעול — השלם סימולציה והפעל 'מוכן ללייב' בהגדרות",
        )
    from politrade.api.clob_client import ClobClientWrapper
    from politrade.crypto.strategy import BetSide, StrategyDecision, DecisionAction
    from politrade.crypto.window import WindowPhase

    clob = ClobClientWrapper(config)
    try:
        crypto_asset = CryptoAsset(asset.lower())
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid asset") from None

    wts = window_ts if window_ts > 0 else compute_window_ts()
    window = fetch_window_market(crypto_asset, wts, config=config)
    if window is None:
        raise HTTPException(status_code=404, detail="market not found")

    if window.phase() == WindowPhase.CLOSED or window.closed:
        raise HTTPException(status_code=400, detail="market closed")

    feed = get_price_feed()
    oracle = feed.get_snapshot(window)
    tokens = fetch_token_prices(clob, window)

    if side.lower() not in ("up", "down"):
        raise HTTPException(status_code=400, detail="side must be up or down")

    bet_side = BetSide(side.lower())
    token_id = window.up_token_id if bet_side == BetSide.UP else window.down_token_id
    ask = tokens.up_ask or tokens.up_mid if bet_side == BetSide.UP else tokens.down_ask or tokens.down_mid

    if clob.is_configured and not clob.has_buy_liquidity(token_id):
        raise HTTPException(status_code=400, detail="no liquidity")

    manual_decision = StrategyDecision(
        action=DecisionAction.BET,
        side=bet_side,
        token_id=token_id,
        entry_ask=ask,
        edge_pct=edge_pct_from_ask(ask),
        reason="הימור ידני",
    )
    executor = CryptoBetExecutor(config, repo, clob)
    bet = executor.execute_bet(window, manual_decision, bet_usd=amount, open_oracle_price=oracle.open_price)
    if bet is None:
        if repo.has_crypto_bet_for_window(crypto_asset.value, wts):
            raise HTTPException(status_code=400, detail="already bet this window")
        raise HTTPException(status_code=400, detail="bet failed")
    invalidate_wallet_cache()
    return {"ok": True, "bet_id": bet.id}


@app.get("/api/portfolio/market")
def api_portfolio_market(slug: str, _: None = Depends(_verify)) -> dict:
    config = get_effective_config()
    try:
        return fetch_market_preview(slug, config=config)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)[:120]) from exc


@app.post("/api/portfolio/buy")
def api_portfolio_buy(
    token_id: str = Form(...),
    amount_usd: float = Form(...),
    title: str = Form(""),
    _: None = Depends(_verify),
) -> dict:
    config = get_effective_config()
    repo = Repository(config)
    if not is_live_enabled(repo):
        raise HTTPException(status_code=403, detail="מסחר אמיתי נעול")
    result = execute_portfolio_buy(
        token_id,
        amount_usd,
        title=title,
        config=config,
        repo=repo,
    )
    if result.ok:
        invalidate_wallet_cache()
    return result.to_dict()


@app.post("/api/portfolio/sell")
def api_portfolio_sell(
    token_id: str = Form(...),
    shares: float = Form(0),
    title: str = Form(""),
    _: None = Depends(_verify),
) -> dict:
    config = get_effective_config()
    repo = Repository(config)
    if not is_live_enabled(repo):
        raise HTTPException(status_code=403, detail="מסחר אמיתי נעול")
    sell_shares = None if shares <= 0 else shares
    result = execute_portfolio_sell(
        token_id,
        sell_shares,
        title=title,
        config=config,
        repo=repo,
    )
    if result.ok:
        invalidate_wallet_cache()
    return result.to_dict()


@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, _: None = Depends(_verify)) -> HTMLResponse:
    config = get_effective_config()
    repo = Repository(config)
    can_live, live_reason = can_enable_live(repo)
    from politrade.crypto.sim_mode import get_readiness_score, get_trading_mode

    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "settings": load_user_settings(repo),
            "wallet": wallet_status(config),
            "trading_mode": get_trading_mode(repo),
            "readiness_score": get_readiness_score(repo),
            "can_enable_live": can_live,
            "live_reason": live_reason,
        },
    )


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, _: None = Depends(_verify)) -> HTMLResponse:
    ctx = _dashboard_context()
    ctx["request"] = request
    return templates.TemplateResponse(request, "dashboard.html", ctx)


@app.get("/scan", response_class=HTMLResponse)
def scan_page(_: None = Depends(_verify)) -> RedirectResponse:
    return RedirectResponse(url="/crypto", status_code=302)


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
    min_profit_pct = float(settings.get("min_leader_profit_pct", 25))
    fallback_pct = float(settings.get("min_leader_profit_pct_fallback", 10))

    for t in candidates:
        should_fetch = force_all and refreshed < max_refresh
        err: str | None = None
        stale = False

        result, fetch_err, stale = fetch_leader_opportunities_safe(
            t.address,
            t.score,
            config=config,
            limit=per_leader,
            force_refresh=should_fetch,
            use_cache=not should_fetch,
        )
        if fetch_err:
            err = fetch_err
        if should_fetch:
            refreshed += 1
        if err and not rate_warning:
            rate_warning = err

        diag = result.diagnostics
        leader_cards.append(
            {
                "trader": t,
                "opportunities": result.items,
                "recent_opportunities": result.recent_items,
                "position_opportunities": result.position_items,
                "scanned": result.scanned,
                "relaxed_filter": result.relaxed,
                "used_min_pct": result.used_min_pct if result.used_min_pct else min_profit_pct,
                "cache_stale": stale,
                "load_error": err,
                "diagnostics": diag,
                "diag_summary": diag.summary_he(),
                "diag_rejections": diag.rejections_he(),
            }
        )

        if err and not rate_warning:
            rate_warning = err

    hot_markets: list = []
    if force_all:
        try:
            hot_markets = fetch_hot_market_opportunities(config, market_limit=5)
        except Exception as exc:
            log.warning("hot_markets_failed: %s", exc)

    runner = get_bot_runner()
    dry_default = runner.mode == "watch" or not runner.is_running
    opportunity_mode = str(settings.get("opportunity_mode", "recent_trades"))
    max_position_usd = float(config.risk.get("max_position_usd", 50))

    return templates.TemplateResponse(
        request,
        "trades.html",
        {
            "leader_cards": leader_cards,
            "hot_markets": hot_markets,
            "opportunity_mode": opportunity_mode,
            "max_trade_age_hours": int(settings.get("max_trade_age_hours", 48)),
            "dry_default": dry_default,
            "clob_configured": config.clob_configured,
            "max_position_usd": max_position_usd,
            "default_invest_usd": max_position_usd,
            "rate_warning": rate_warning,
            "min_profit_pct": min_profit_pct,
            "fallback_pct": fallback_pct,
            "display_k": display_k,
        },
    )


@app.get("/trades", response_class=HTMLResponse)
def trades_page(_: None = Depends(_verify)) -> RedirectResponse:
    return RedirectResponse(url="/crypto", status_code=302)


@app.get("/leaders", response_class=HTMLResponse)
def leaders_redirect(_: None = Depends(_verify)) -> RedirectResponse:
    return RedirectResponse(url="/crypto", status_code=302)


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
    crypto_bet_usd: float = Form(5),
    crypto_min_edge_pct: float = Form(0),
    crypto_max_entry_price: float = Form(0.99),
    crypto_min_move_pct: float = Form(0),
    crypto_no_bet_first_seconds: int = Form(0),
    crypto_no_bet_last_seconds: int = Form(0),
    crypto_strategy_mode: str = Form("follow_oracle"),
    crypto_assets: str = Form("btc"),
    crypto_auto_bet: str = Form("0"),
    sim_start_balance: float = Form(1000),
    sim_auto_learn: str = Form("1"),
    _: None = Depends(_verify),
) -> RedirectResponse:
    from politrade.crypto.window import reset_phase_cfg_cache

    config = get_effective_config()
    repo = Repository(config)
    save_user_settings(
        repo,
        {
            "crypto_bet_usd": crypto_bet_usd,
            "crypto_min_edge_pct": crypto_min_edge_pct,
            "crypto_max_entry_price": crypto_max_entry_price,
            "crypto_min_move_pct": crypto_min_move_pct,
            "crypto_no_bet_first_seconds": crypto_no_bet_first_seconds,
            "crypto_no_bet_last_seconds": crypto_no_bet_last_seconds,
            "crypto_strategy_mode": crypto_strategy_mode,
            "crypto_assets": crypto_assets,
            "crypto_auto_bet": crypto_auto_bet,
            "sim_start_balance": sim_start_balance,
            "sim_auto_learn": sim_auto_learn,
        },
    )
    set_auto_learn(repo, sim_auto_learn in ("1", "on", "true"))
    reset_phase_cfg_cache()
    get_sim_runner().set_auto_sim(crypto_auto_bet in ("1", "on", "true"))
    if is_live_enabled(repo):
        get_crypto_runner().set_auto_bet(crypto_auto_bet in ("1", "on", "true"))
    return RedirectResponse(url="/settings?saved=1", status_code=303)


@app.get("/wallet", response_class=HTMLResponse)
def wallet_page(request: Request, _: None = Depends(_verify)) -> HTMLResponse:
    config = get_effective_config()
    repo = Repository(config)
    activity = build_wallet_activity(config, repo)
    sim_bets = [enrich_sim_bet_dict(b) for b in repo.list_sim_bets(50)]
    return templates.TemplateResponse(
        request,
        "wallet.html",
        {
            "wallet": wallet_status(config),
            "sim_balance": repo.get_sim_balance(),
            "sim_start_balance": repo.get_sim_start_balance(),
            "sim_summary": repo.sim_bets_summary(),
            "sim_bets": sim_bets,
            "sim_open": [enrich_sim_bet_dict(b) for b in repo.get_open_sim_bets()],
            "activity": activity,
            "live_enabled": is_live_enabled(repo),
        },
    )


@app.post("/api/wallet")
def api_wallet(
    funder_address: str = Form(...),
    signature_type: int = Form(1),
    private_key: str = Form(""),
    _: None = Depends(_verify),
) -> RedirectResponse:
    config = get_effective_config()
    repo = Repository(config)
    try:
        save_wallet(
            private_key=private_key or None,
            funder_address=funder_address,
            signature_type=signature_type,
            config=config,
            repo=repo,
        )
    except ValueError as exc:
        return RedirectResponse(
            url=f"/settings?error={quote(str(exc))}",
            status_code=303,
        )
    return RedirectResponse(url="/settings?wallet_saved=1", status_code=303)


@app.get("/wallet/activity", response_class=HTMLResponse)
def wallet_activity_page(request: Request, _: None = Depends(_verify)) -> HTMLResponse:
    config = get_effective_config()
    activity = build_wallet_activity(config)
    return templates.TemplateResponse(
        request,
        "wallet_activity.html",
        {"activity": activity},
    )


@app.get("/api/wallet/activity")
def api_wallet_activity(_: None = Depends(_verify)) -> dict:
    activity = build_wallet_activity(get_effective_config())
    return wallet_activity_to_dict(activity)


@app.post("/api/wallet/reset-creds")
def api_wallet_reset_creds(_: None = Depends(_verify)) -> RedirectResponse:
    config = get_effective_config()
    reset_clob_creds(config)
    Repository(config).audit("info", "clob_creds_reset", "manual")
    return RedirectResponse(url="/settings?creds_reset=1", status_code=303)


@app.post("/api/copy-trade")
def api_copy_trade(
    request: Request,
    leader_address: str = Form(...),
    trade_id: str = Form(...),
    token_id: str = Form(...),
    market_id: str = Form(...),
    price: float = Form(0),
    size_usd: float = Form(0),
    invest_usd: float = Form(...),
    market_title: str = Form(""),
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
        "title": market_title,
    }
    signal = selector.build_signal(trade, leader_address)
    if signal is None:
        repo.audit("error", "manual_copy_invalid", trade_id)
        return RedirectResponse(url="/trades?err=invalid", status_code=303)
    if market_title:
        signal.market_title = market_title

    is_dry = dry_run == "1"
    ok, msg = executor.execute_manual(signal, dry_run=is_dry, invest_usd=invest_usd)
    repo.audit("info" if ok else "error", "manual_copy", f"{trade_id} {msg}")
    if ok and not is_dry:
        return RedirectResponse(url="/positions?opened=1", status_code=303)
    if ok:
        return RedirectResponse(url="/trades?copied=1", status_code=303)
    reason = "unknown"
    detail = msg
    if "|" in msg:
        reason, detail = msg.split("|", 1)
    return RedirectResponse(
        url=f"/trades?failed=1&reason={quote(reason)}&detail={quote(detail)}",
        status_code=303,
    )


@app.get("/api/positions/live")
def api_positions_live(_: None = Depends(_verify)) -> dict:
    config = get_effective_config()
    return build_live_positions_summary(config)


@app.get("/positions", response_class=HTMLResponse)
def positions_page(request: Request, _: None = Depends(_verify)) -> HTMLResponse:
    config = get_effective_config()
    repo = Repository(config)
    live = build_live_positions_summary(config, repo)
    return templates.TemplateResponse(
        request,
        "positions.html",
        {
            "open_positions": repo.get_open_positions(),
            "closed_positions": repo.list_closed_positions(),
            "summary": repo.get_closed_positions_summary(),
            "live": live,
            "exit_settings": config.exit,
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


@app.get("/api/status/live")
def api_status_live(_: None = Depends(_verify)) -> dict:
    return build_live_status(get_effective_config())


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


GUIDE_PDF = project_root() / "docs" / "Politrade-Guide-HE-v2.pdf"
if not GUIDE_PDF.is_file():
    GUIDE_PDF = project_root() / "docs" / "Politrade-Guide-HE.pdf"


@app.get("/guide.pdf")
def download_guide_pdf(_: None = Depends(_verify)) -> FileResponse:
    if not GUIDE_PDF.is_file():
        raise HTTPException(status_code=404, detail="Guide PDF not found")
    return FileResponse(
        GUIDE_PDF,
        media_type="application/pdf",
        filename="Politrade-Guide-HE.pdf",
    )


def main() -> None:
    import uvicorn

    config = get_config()
    port = int(os.environ.get("PORT", config.env.port))
    uvicorn.run("politrade.web.app:app", host="0.0.0.0", port=port, reload=False)


if __name__ == "__main__":
    main()
