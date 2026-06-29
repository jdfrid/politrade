"""Capture real Politrade UI screenshots for the user guide."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "guide" / "screenshots"
BASE = os.environ.get("GUIDE_BASE_URL", "http://127.0.0.1:8000")
USER = os.environ.get("GUIDE_AUTH_USER", "admin")
PASS = os.environ.get("GUIDE_AUTH_PASS", "politrade")

PAGES = [
    ("01-crypto.png", "/crypto", 1400, 2200),
    ("02-wallet.png", "/wallet", 1200, 1400),
    ("03-settings.png", "/settings", 1200, 1000),
    ("04-wallet-activity.png", "/wallet/activity", 1200, 1600),
    ("05-logs.png", "/logs", 1200, 900),
]


def _wait_server(url: str, timeout: float = 45.0) -> bool:
    import urllib.request
    import base64

    auth = base64.b64encode(f"{USER}:{PASS}".encode()).decode()
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            req = urllib.request.Request(url, headers={"Authorization": f"Basic {auth}"})
            with urllib.request.urlopen(req, timeout=3) as resp:
                return resp.status == 200
        except Exception:
            time.sleep(0.8)
    return False


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    proc = None
    base = BASE.rstrip("/")

    if "127.0.0.1" in base or "localhost" in base:
        proc = subprocess.Popen(
            [str(ROOT / ".venv" / "Scripts" / "politrade-web.exe")],
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if not _wait_server(f"{base}/health"):
            if proc:
                proc.terminate()
            raise SystemExit("Local server did not start in time")

    from playwright.sync_api import sync_playwright

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            context = browser.new_context(
                viewport={"width": 1440, "height": 900},
                locale="he-IL",
                http_credentials={"username": USER, "password": PASS},
            )
            page = context.new_page()
            for name, path, width, height in PAGES:
                page.set_viewport_size({"width": width, "height": min(height, 900)})
                page.goto(f"{base}{path}", wait_until="networkidle", timeout=60000)
                if path == "/crypto":
                    try:
                        page.wait_for_function(
                            "() => { const b = document.getElementById('crypto-markets-body'); "
                            "return b && !b.textContent.includes('טוען'); }",
                            timeout=20000,
                        )
                    except Exception:
                        page.wait_for_timeout(5000)
                else:
                    page.wait_for_timeout(2000)
                target = OUT / name
                page.screenshot(path=str(target), full_page=True)
                print(f"Captured {target.name} ({target.stat().st_size // 1024} KB)")
            browser.close()
    finally:
        if proc:
            proc.terminate()
            proc.wait(timeout=10)


if __name__ == "__main__":
    main()
