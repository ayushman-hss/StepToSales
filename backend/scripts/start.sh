#!/bin/sh
# Container entry point: prepare the database, then run the one API process
# (the live simulator and the Telegram bot must run in exactly one).
set -e
cd "$(dirname "$0")/.."
python scripts/boot.py
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" \
  --proxy-headers --forwarded-allow-ips='*'
