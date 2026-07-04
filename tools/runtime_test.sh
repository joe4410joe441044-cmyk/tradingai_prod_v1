#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

echo "===== start paper bot ====="
curl -s -X POST http://127.0.0.1:8001/api/bot/start \
  -H "Content-Type: application/json" \
  -d '{"symbol":"XRPUSDT","mode":"paper","risk_percent":1,"sl_percent":0.5,"tp_percent":1,"leverage":5}' | jq

sleep 3

echo
echo "===== status after start ====="
curl -s http://127.0.0.1:8001/api/bot/status | jq

echo
echo "===== stop bot ====="
curl -s -X POST http://127.0.0.1:8001/api/bot/stop | jq

sleep 3

echo
echo "===== status after stop ====="
curl -s http://127.0.0.1:8001/api/bot/status | jq
