#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/dxsb}"
SERVICE_NAME="${SERVICE_NAME:-dxsb}"
BRANCH="${BRANCH:-main}"

if [[ ! -d "$APP_DIR/.git" ]]; then
  echo "Repo not found at $APP_DIR"
  exit 1
fi

cd "$APP_DIR"

git fetch origin
git checkout "$BRANCH"
git pull --ff-only origin "$BRANCH"

source .venv/bin/activate
pip install -r requirements.txt

sudo systemctl restart "$SERVICE_NAME"
sudo systemctl status "$SERVICE_NAME" --no-pager

echo "Update complete. Logs: journalctl -u ${SERVICE_NAME} -f"
