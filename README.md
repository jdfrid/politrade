# Politrade

Personal Polymarket copy-trading bot. Discovers successful traders, copies selected BUY signals with risk limits, and exits when profit targets are met (default: 2x entry cost).

## Requirements

- Python 3.11+
- Polymarket account with pUSD balance on Polygon
- Private key and funder address for API trading

## Setup

```bash
cd politrade
python -m venv .venv
.venv\Scripts\activate   # Windows
pip install -e ".[dev]"
copy .env.example .env   # then edit with your keys
```

## Configuration

- `config/settings.yaml` — scoring, risk, polling intervals
- `.env` — secrets (`PRIVATE_KEY`, `FUNDER_ADDRESS`)

## Usage

```bash
# Rank and store top leaders
politrade scan

# Dry-run: log signals without trading
politrade watch

# Live trading (requires .env)
politrade trade

# PnL report
politrade report

# Single iteration
politrade watch --once
```

## Kill switch

Create a file named `STOP_TRADING` in the project root to halt all new orders.

## Safety

- Start with `watch` mode for at least a week
- Use small `max_position_usd` values initially
- Never commit `.env` or private keys
- Trading prediction markets may be regulated in your jurisdiction

## Architecture

See the project plan for full module breakdown: Data API (analysis), CLOB V2 (execution), SQLite (state).

## Deploy on Render

1. Push this repo to [github.com/jdfrid/politrade](https://github.com/jdfrid/politrade).
2. In [Render](https://render.com): **New → Blueprint** → connect the repo (uses `render.yaml`).
3. Set **secret** environment variables in the Render dashboard:
   - `PRIVATE_KEY` — wallet private key
   - `FUNDER_ADDRESS` — Polymarket funder address
   - Optional: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`
4. **Worker** service runs continuously (`python -m politrade.main trade`).
5. SQLite and CLOB API creds are stored on the attached disk at `/var/data` (survives restarts).

| Variable | Default | Description |
|----------|---------|-------------|
| `POLITRADE_MODE` | `trade` | `watch` = dry-run, `trade` = live |
| `KILL_SWITCH` | — | Set to `1` to stop new orders |
| `DATABASE_URL` | `sqlite:////var/data/politrade.db` | DB path on Render disk |

**Safety:** Start with `POLITRADE_MODE=watch` on Render, verify logs, then switch to `trade`.
