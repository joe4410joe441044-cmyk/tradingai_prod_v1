#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

echo "===== restart tradingbot.service ====="
sudo systemctl restart tradingbot.service

sleep 3

echo
echo "===== service ====="
systemctl status tradingbot.service --no-pager

echo
echo "===== health ====="
curl -s http://127.0.0.1:8001/ | jq

echo
echo "===== bot status ====="
curl -s http://127.0.0.1:8001/api/bot/status | jq
