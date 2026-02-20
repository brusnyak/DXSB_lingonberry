#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/dxsb}"
SERVICE_NAME="${SERVICE_NAME:-dxsb}"
LINUX_USER="${LINUX_USER:-$USER}"
REPO_URL="${REPO_URL:-https://github.com/brusnyak/DXSB_lingonberry.git}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

if ! command -v git >/dev/null 2>&1; then
  echo "git is required"
  exit 1
fi

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "$PYTHON_BIN is required"
  exit 1
fi

if [[ ! -d "$APP_DIR/.git" ]]; then
  sudo mkdir -p "$(dirname "$APP_DIR")"
  sudo git clone "$REPO_URL" "$APP_DIR"
  sudo chown -R "$LINUX_USER":"$LINUX_USER" "$APP_DIR"
fi

cd "$APP_DIR"

if [[ ! -d .venv ]]; then
  "$PYTHON_BIN" -m venv .venv
fi

source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

if [[ ! -f .env ]]; then
  cat > .env <<'EOF'
TELEGRAM_BOT_TOKEN=REPLACE_ME
TELEGRAM_CHAT_ID=REPLACE_ME
EOF
  echo "Created $APP_DIR/.env, edit it before starting service"
fi

sudo tee "/etc/systemd/system/${SERVICE_NAME}.service" >/dev/null <<EOF
[Unit]
Description=DXSB Lingonberry Bot
After=network.target

[Service]
Type=simple
User=${LINUX_USER}
WorkingDirectory=${APP_DIR}
EnvironmentFile=${APP_DIR}/.env
ExecStart=${APP_DIR}/.venv/bin/python ${APP_DIR}/dex_bot.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"
sudo systemctl restart "$SERVICE_NAME"
sudo systemctl status "$SERVICE_NAME" --no-pager

echo "Deploy complete. Logs: journalctl -u ${SERVICE_NAME} -f"
