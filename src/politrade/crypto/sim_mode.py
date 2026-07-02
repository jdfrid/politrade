"""Simulation vs live trading mode."""

from __future__ import annotations

from politrade.storage.repository import Repository

TRADING_MODE_KEY = "sim_trading_mode"
SIM_AUTO_LEARN_KEY = "sim_auto_learn"
READINESS_SCORE_KEY = "sim_readiness_score"

MODE_SIMULATION = "simulation_only"
MODE_LIVE = "live_enabled"

READINESS_THRESHOLD = 70.0
READINESS_MIN_CYCLES = 10


def get_trading_mode(repo: Repository | None = None) -> str:
    r = repo or Repository()
    raw = r.get_state(TRADING_MODE_KEY)
    if raw == MODE_LIVE:
        return MODE_LIVE
    return MODE_SIMULATION


def set_trading_mode(repo: Repository, mode: str) -> None:
    if mode not in (MODE_SIMULATION, MODE_LIVE):
        mode = MODE_SIMULATION
    repo.set_state(TRADING_MODE_KEY, mode)


def is_live_enabled(repo: Repository | None = None) -> bool:
    return get_trading_mode(repo) == MODE_LIVE


def is_auto_learn_enabled(repo: Repository | None = None) -> bool:
    r = repo or Repository()
    raw = r.get_state(SIM_AUTO_LEARN_KEY)
    if raw is not None:
        return raw == "1"
    from politrade.web.user_settings import load_user_settings

    return bool(load_user_settings(r).get("sim_auto_learn", False))


def set_auto_learn(repo: Repository, enabled: bool) -> None:
    repo.set_state(SIM_AUTO_LEARN_KEY, "1" if enabled else "0")


def get_readiness_score(repo: Repository | None = None) -> float:
    r = repo or Repository()
    raw = r.get_state(READINESS_SCORE_KEY)
    if raw is None:
        return 0.0
    try:
        return float(raw)
    except ValueError:
        return 0.0


def set_readiness_score(repo: Repository, score: float) -> None:
    repo.set_state(READINESS_SCORE_KEY, str(round(max(0.0, min(100.0, score)), 1)))


def can_enable_live(repo: Repository | None = None) -> tuple[bool, str]:
    r = repo or Repository()
    score = get_readiness_score(r)
    cycles = r.list_sim_cycles(limit=READINESS_MIN_CYCLES + 1)
    if len(cycles) < READINESS_MIN_CYCLES:
        return False, f"נדרשים לפחות {READINESS_MIN_CYCLES} סיבובי סימולציה (יש {len(cycles)})"
    if score < READINESS_THRESHOLD:
        return False, f"ציון מוכנות {score:.0f} < {READINESS_THRESHOLD:.0f}"
    return True, "מוכן ללייב"


def ensure_live_crypto_runner(repo: Repository | None = None) -> dict[str, Any]:
    """Start crypto runner when live mode is on (self-heal after Render restart)."""
    from politrade.crypto.runner import get_crypto_runner
    from politrade.web.user_settings import load_user_settings

    r = repo or Repository()
    runner = get_crypto_runner()
    if not is_live_enabled(r):
        return {"live": False, "running": runner.is_running}

    settings = load_user_settings(r)
    auto = settings.get("crypto_auto_bet", True)
    if not runner.is_running:
        runner.start()
    runner.set_auto_bet(bool(auto))
    return {
        "live": True,
        "running": runner.is_running,
        "auto_bet": bool(auto),
        "ticks": runner.status.get("ticks", 0),
    }
