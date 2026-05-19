"""Politrade CLI and main orchestration loop."""

from __future__ import annotations

import argparse
import signal
import sys
import time

from politrade.analysis.leader_scanner import LeaderScanner
from politrade.bot_runner import BotRunner
from politrade.config import AppConfig, get_config
from politrade.logging_setup import get_logger, setup_logging
from politrade.storage.repository import Repository

log = get_logger(__name__)


def cmd_scan(config: AppConfig) -> int:
    scanner = LeaderScanner(config)
    ranked = scanner.scan()
    print(f"\nTop {len(ranked)} leaders:")
    for i, r in enumerate(ranked, 1):
        name = r.get("username") or r["address"][:12]
        print(f"  {i}. {name} — score={r['score']:.1f} trades={r['metrics']['trade_count']}")
    return 0


def cmd_report(config: AppConfig) -> int:
    repo = Repository(config)
    summary = repo.get_closed_positions_summary()
    open_pos = repo.get_open_positions()
    print("\n=== Politrade Report ===")
    print(f"Open positions: {len(open_pos)}")
    print(f"Closed trades:  {summary['closed_count']}")
    print(f"Wins / Losses:  {summary['win_count']} / {summary['loss_count']}")
    print(f"Realized PnL:   ${summary['total_realized_pnl']:.2f}")
    exposure = repo.total_open_exposure()
    print(f"Open exposure:  ${exposure:.2f}")
    if open_pos:
        print("\nOpen:")
        for p in open_pos:
            print(
                f"  #{p.id} market={p.market_id[:16]}... "
                f"cost=${p.entry_cost_usd:.2f} shares={p.shares:.4f}"
            )
    return 0


def run_loop(mode: str, config: AppConfig, once: bool = False) -> int:
    runner = BotRunner(config)
    if once:
        runner.run_iteration_once(mode)  # type: ignore[arg-type]
        return 0

    def _handle_signal(*_args) -> None:
        runner.stop()
        log.info("shutdown_requested")

    signal.signal(signal.SIGINT, _handle_signal)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _handle_signal)

    runner.start(mode)  # type: ignore[arg-type]
    try:
        while runner.is_running:
            time.sleep(1)
    except KeyboardInterrupt:
        runner.stop()
    return 0


def main(argv: list[str] | None = None) -> int:
    setup_logging()
    parser = argparse.ArgumentParser(description="Politrade — Polymarket copy trading bot")
    parser.add_argument(
        "mode",
        choices=["scan", "watch", "trade", "report"],
        help="scan=rank leaders, watch=dry-run, trade=live, report=PnL",
    )
    parser.add_argument("--once", action="store_true", help="Run one iteration then exit")
    args = parser.parse_args(argv)

    config = get_config()

    if args.mode == "scan":
        return cmd_scan(config)
    if args.mode == "report":
        return cmd_report(config)
    return run_loop(args.mode, config, once=args.once)


if __name__ == "__main__":
    sys.exit(main())
