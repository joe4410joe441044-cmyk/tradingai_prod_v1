#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

echo "===== frontend playwright e2e ====="
cd frontend
npx playwright test
