#!/usr/bin/env bash
set -euo pipefail

LINES="${1:-120}"

echo "===== tradingbot logs last ${LINES} lines ====="
journalctl -u tradingbot.service -n "$LINES" --no-pager
