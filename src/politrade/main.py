"""Politrade CLI and main orchestration loop."""

from __future__ import annotations

import argparse
import signal
import sys
import time
from datetime import datetime, timezone

from politrade.analysis.leader_scanner import LeaderScanner
from politrade.api.data_client import DataClient
from politrade.config import AppConfig, get_config
from politrade.execution.exit_monitor import ExitMonitor
from politrade.execution.order_executor import OrderExecutor
from politrade.logging_setup import get_logger, setup_logging
from politrade.signals.copy_detector import CopyDetector
from politrade.storage.repository import Repository

log = get_logger(__name__)
_running = True


def _handle_signal(*_args) -> None:
    global _running
    _running = False
    log.info("shutdown_requested")


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


def _should_rescan(config: AppConfig, repo: Repository) -> bool:
    last = repo.get_state("last_leader_scan")
    if not last:
        return True
    try:
        last_dt = datetime.fromisoformat(last)
        if last_dt.tzinfo is None:
            last_dt = last_dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return True
    hours = int(config.leaders.get("rescan_hours", 12))
    elapsed = (datetime.now(timezone.utc) - last_dt).total_seconds() / 3600
    return elapsed >= hours


def run_loop(mode: str, config: AppConfig, once: bool = False) -> int:
    global _running
    signal.signal(signal.SIGINT, _handle_signal)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _handle_signal)

    repo = Repository(config)
    data = DataClient(config)
    scanner = LeaderScanner(config, data, repo)
    detector = CopyDetector(config, data, repo)
    executor = OrderExecutor(config, repo)
    exit_mon = ExitMonitor(config, repo)

    dry_run = mode in ("watch",)
    poll_seconds = int(config.copy.get("poll_seconds", 45))
    exit_seconds = int(config.exit.get("monitor_seconds", 20))
    last_exit_check = 0.0

    log.info("loop_started", mode=mode, dry_run=dry_run)

    try:
        while _running:
            if _should_rescan(config, repo):
                scanner.scan()
                repo.set_state("last_leader_scan", datetime.now(timezone.utc).isoformat())

            if mode in ("watch", "trade"):
                signals = detector.poll()
                for sig in signals:
                    if mode == "trade":
                        executor.execute(sig, dry_run=False)
                    else:
                        executor.execute(sig, dry_run=True)

            now = time.monotonic()
            if mode == "trade" and (now - last_exit_check) >= exit_seconds:
                exit_mon.check_all(dry_run=False)
                last_exit_check = now
            elif mode == "watch" and (now - last_exit_check) >= exit_seconds:
                exit_mon.check_all(dry_run=True)
                last_exit_check = now

            if once:
                break
            time.sleep(poll_seconds)
    finally:
        data.close()

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
