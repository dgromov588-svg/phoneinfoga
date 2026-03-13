#!/usr/bin/env bash
set -euo pipefail

BOT_DIR="/home4/framexyz/phoneinfoga"
PYTHON_BIN="/home4/framexyz/virtualenv/phoneinfoga/3.11/bin/python3.11_bin"
SCREEN_BIN="/usr/bin/screen"
LOCK_FILE="/tmp/phoneinfoga_telegram_bot.lock"
LOG_FILE="/home4/framexyz/phoneinfoga/telegram_bot_watchdog.log"

# If bot is already running, exit.
if pgrep -f "telegram_bot.py" >/dev/null 2>&1; then
  exit 0
fi

{
  echo "$(date -u '+%Y-%m-%dT%H:%M:%SZ') watchdog: bot not running, starting..."
  rm -f "$LOCK_FILE"
  "$SCREEN_BIN" -S phoneinfoga_bot -X quit || true
  cd "$BOT_DIR"
  "$SCREEN_BIN" -dmS phoneinfoga_bot "$PYTHON_BIN" telegram_bot.py
} >> "$LOG_FILE" 2>&1
