#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

echo "===== stop bot ====="
curl -s -X POST http://127.0.0.1:8001/api/bot/stop | jq

sleep 3

echo
echo "===== bot status ====="
curl -s http://127.0.0.1:8001/api/bot/status | jq
