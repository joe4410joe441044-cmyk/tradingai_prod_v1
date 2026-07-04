#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

SYMBOL="${1:-XRPUSDT}"
MODE="${2:-paper}"

echo "===== start bot ====="
curl -s -X POST http://127.0.0.1:8001/api/bot/start \
  -H "Content-Type: application/json" \
  -d "{\"symbol\":\"${SYMBOL}\",\"mode\":\"${MODE}\",\"risk_percent\":1,\"sl_percent\":0.5,\"tp_percent\":1,\"leverage\":5}" | jq

sleep 3

echo
echo "===== bot status ====="
curl -s http://127.0.0.1:8001/api/bot/status | jq
