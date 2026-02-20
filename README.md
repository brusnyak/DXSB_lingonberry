# DXSB Lingonberry MVP

Semi-automated signal bot for DexScreener markets (Solana + EVM):
- Finds candidate pairs
- Applies safety checks (honeypot/rugcheck + gas/slippage guards)
- Sends manual-execution Telegram alerts
- Tracks open signal outcomes to build 2-week validation stats

## Important security note
If your old Telegram bot token was exposed, rotate it in BotFather before running this bot.

## What this bot does
- Alert-only workflow (you execute manually)
- Position sizing from bankroll and risk-per-quality rules
- Liquidity-based stop + RR-based take-profit targets
- Blocks signal generation during low-liquidity local hours

## What this bot does not do (yet)
- Direct wallet execution
- Full backtesting engine
- Web dashboard

## Setup
1. Create a Python virtual environment and install deps:
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2. Configure:
- Edit `config.json`
- Or set env vars:
  - `TELEGRAM_BOT_TOKEN`
  - `TELEGRAM_CHAT_ID`
  - `cp .env.example .env` and export from shell if preferred

3. Run:
```bash
python3 dex_bot.py
```

4. Check 14-day validation stats:
```bash
python3 stats_report.py --db dex_analytics.db --days 14
```

## Telegram alert format
Top section = quick decision fields (quality, entry, SL/TP, size).
After `========` = context (score, liquidity, volume, age, slippage, link).

Execution links are configured per chain in `config.json` under `execution_links`.
Replace defaults with your personal referral/deep links as needed.

## Recommended deployment (no Docker)
Use Ubuntu VPS + `systemd`.

One-command scripts are included:
- `/Users/yegor/Documents/Agency & Security Stuff/Development/dexscreener-bot/scripts/deploy.sh`
- `/Users/yegor/Documents/Agency & Security Stuff/Development/dexscreener-bot/scripts/update.sh`

First deploy on VPS:
```bash
APP_DIR=/opt/dxsb LINUX_USER=$USER bash scripts/deploy.sh
```

Update after new push:
```bash
APP_DIR=/opt/dxsb BRANCH=main bash scripts/update.sh
```

Example unit file (`/etc/systemd/system/dxsb.service`):
```ini
[Unit]
Description=DXSB Lingonberry Bot
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/opt/dxsb
Environment=TELEGRAM_BOT_TOKEN=REPLACE_ME
Environment=TELEGRAM_CHAT_ID=REPLACE_ME
ExecStart=/opt/dxsb/.venv/bin/python /opt/dxsb/dex_bot.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Then:
```bash
sudo systemctl daemon-reload
sudo systemctl enable dxsb
sudo systemctl start dxsb
sudo systemctl status dxsb
journalctl -u dxsb -f
```

## Validation gate before live capital
Target gate:
- >= 14 days paper data
- >= 60 closed signals
- Win rate >= 70%
- Profit factor >= 2.0
- Max drawdown <= 10%

## Repo workflow
You can push this project to your new repo:
- [DXSB_lingonberry](https://github.com/brusnyak/DXSB_lingonberry.git)

Example:
```bash
git remote add origin https://github.com/brusnyak/DXSB_lingonberry.git
git add .
git commit -m \"Build DXSB semi-auto MVP\"
git push -u origin main
```

Vercel is suitable for a dashboard/UI later, not for this always-on bot process.
