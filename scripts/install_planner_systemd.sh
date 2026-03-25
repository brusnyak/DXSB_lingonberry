#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-$HOME/DXSB_lingonberry}"
SYSTEMD_DIR="${SYSTEMD_DIR:-/etc/systemd/system}"
LINUX_USER="${LINUX_USER:-$USER}"

if [[ ! -d "$APP_DIR" ]]; then
  echo "App dir not found: $APP_DIR"
  exit 1
fi

tmp_service="$(mktemp)"
tmp_report_service="$(mktemp)"
sed "s#/home/ubuntu/DXSB_lingonberry#${APP_DIR}#g; s#User=ubuntu#User=${LINUX_USER}#g" "$APP_DIR/deploy/systemd/dxsb-planner.service" > "$tmp_service"
sed "s#/home/ubuntu/DXSB_lingonberry#${APP_DIR}#g; s#User=ubuntu#User=${LINUX_USER}#g" "$APP_DIR/deploy/systemd/dxsb-planner-report.service" > "$tmp_report_service"

sudo install -m 0644 "$tmp_service" "${SYSTEMD_DIR}/dxsb-planner.service"
sudo install -m 0644 "$APP_DIR/deploy/systemd/dxsb-planner.timer" "${SYSTEMD_DIR}/dxsb-planner.timer"
sudo install -m 0644 "$tmp_report_service" "${SYSTEMD_DIR}/dxsb-planner-report.service"
sudo install -m 0644 "$APP_DIR/deploy/systemd/dxsb-planner-report.timer" "${SYSTEMD_DIR}/dxsb-planner-report.timer"
rm -f "$tmp_service" "$tmp_report_service"

sudo systemctl daemon-reload
sudo systemctl enable dxsb-planner.timer
sudo systemctl enable dxsb-planner-report.timer
sudo systemctl restart dxsb-planner.timer
sudo systemctl restart dxsb-planner-report.timer
sudo systemctl start dxsb-planner.service
sudo systemctl status dxsb-planner.timer --no-pager
sudo systemctl status dxsb-planner-report.timer --no-pager
