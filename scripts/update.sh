#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-$HOME/DXSB_lingonberry}"
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

if systemctl list-unit-files | grep -q '^dxsb-planner.timer'; then
  sudo systemctl restart dxsb-planner.timer
  sudo systemctl restart dxsb-planner-report.timer
  sudo systemctl start dxsb-planner.service || true
  sudo systemctl status dxsb-planner.timer --no-pager
  sudo systemctl status dxsb-planner-report.timer --no-pager
elif systemctl list-unit-files | grep -q "^${SERVICE_NAME}.service"; then
  sudo systemctl restart "$SERVICE_NAME"
  sudo systemctl status "$SERVICE_NAME" --no-pager
else
  echo "No managed systemd unit found. Code and dependencies updated only."
fi

echo "Update complete. Logs: journalctl -u ${SERVICE_NAME} -f"
