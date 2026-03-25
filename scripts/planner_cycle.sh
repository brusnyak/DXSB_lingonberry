#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
PYTHON_BIN="${PYTHON_BIN:-$APP_DIR/.venv/bin/python}"
SEND_REPORT="${SEND_REPORT:-0}"

cd "$APP_DIR"

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Python runtime not found at $PYTHON_BIN"
  exit 1
fi

"$PYTHON_BIN" cli.py portfolio sync
"$PYTHON_BIN" cli.py research sync-earn
"$PYTHON_BIN" cli.py strategy scan-spot
"$PYTHON_BIN" cli.py strategy scan-research

if [[ "$SEND_REPORT" == "1" ]]; then
  "$PYTHON_BIN" cli.py report research --telegram
  "$PYTHON_BIN" cli.py report daily --telegram
else
  "$PYTHON_BIN" cli.py report research
  "$PYTHON_BIN" cli.py report daily
fi
