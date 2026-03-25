# DXSB Lingonberry

Binance-focused research and portfolio planner for a two-sleeve workflow:

- `Earn sleeve`: track yield parking and Simple Earn opportunities
- `Spot sleeve`: research-only catalyst and pullback ideas for manual execution
- `Reporting`: portfolio, blocked ideas, research watchlist, and Simple Earn board

## Current scope

- Manual execution only
- Binance account sync
- Simple Earn offer sync
- Binance research scan from live Earn offers plus market context
- Telegram plain-text reporting

Legacy DexScreener and ICT scanner logic is no longer part of the active planner flow. The old chart helpers may still remain in the repo for reference, but legacy scanner commands are deprecated.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Configure:

- `BINANCE_API_KEY`
- `BINANCE_SECRET_KEY`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

## Main commands

```bash
python3 cli.py portfolio sync
python3 cli.py research sync-earn
python3 cli.py strategy scan-research
python3 cli.py report daily
```

Manual event ingestion:

```bash
python3 cli.py research ingest-events --file data/events/manual_events.json
```

## Timed planner cycle

```bash
scripts/planner_cycle.sh
```

It runs:

1. `portfolio sync`
2. `research sync-earn`
3. `strategy scan-spot`
4. `strategy scan-research`
5. `report daily`

## Deployment helpers

```bash
make test
make planner-sync
make planner-report
make server-update
make server-install-services
```

## Telegram daemon

`scripts/telegram_daemon.py` now acts as a thin planner wrapper. Legacy `/scan`, `/monitor`, and `/invest` commands are intentionally deprecated there to avoid accidental use of the old DexScreener workflow.
