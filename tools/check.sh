#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

echo "===== git status ====="
git status --short

echo
echo "===== latest commit ====="
git log -1 --oneline

echo
echo "===== git diff --check ====="
git diff --check

echo
echo "===== compile backend ====="
./venv/bin/python -m compileall backend

echo
echo "===== runtime health tests ====="
./venv/bin/python -m unittest tests/test_runtime_health_snapshot.py

echo
echo "===== account source metadata tests ====="
./venv/bin/python -m unittest tests/test_exchange_live_status.py

echo
echo "===== runtime ai debug tests ====="
./venv/bin/python -m unittest tests/test_runtime_ai_debug.py
