#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

echo "===== git ====="
git status --short
git log -1 --oneline

echo
echo "===== service ====="
systemctl status tradingbot.service --no-pager || true

echo
echo "===== health ====="
curl -s http://127.0.0.1:8001/ | jq

echo
echo "===== bot status ====="
curl -s http://127.0.0.1:8001/api/bot/status | jq
