#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

echo "===== backend check ====="
./tools/check.sh

echo
echo "===== frontend build ====="
cd frontend
npm run build
