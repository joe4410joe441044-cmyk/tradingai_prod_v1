#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

PLAYWRIGHT_CONFIG="frontend/playwright.config.js"
VITE_PLAYWRIGHT_CONFIG="frontend/vite.playwright.config.js"

if grep -nE '35\.194\.104\.74|:8001|vite\.config\.js' \
    "$PLAYWRIGHT_CONFIG" \
    "$VITE_PLAYWRIGHT_CONFIG"; then
    echo "Playwright isolation guard failed: production proxy reference found." >&2
    exit 1
fi

if grep -nE 'proxy[[:space:]]*:' "$VITE_PLAYWRIGHT_CONFIG"; then
    echo "Playwright isolation guard failed: proxy is not allowed." >&2
    exit 1
fi

export PLAYWRIGHT_PRODUCTION_ISOLATION=1
export VITE_PLAYWRIGHT=1
unset VITE_API_BASE
unset VITE_WS_BASE
unset VITE_WS_URL

echo "===== frontend playwright e2e ====="
cd frontend
npx playwright test --config playwright.config.js "$@"
