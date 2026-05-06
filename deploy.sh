#!/bin/bash

set -e

# =========================
# CONFIG
# =========================
APP_DIR="$HOME/tradingai_prod_v1"
SERVICE_NAME="tradingai"
BRANCH="main"

echo "🚀 ===== DEPLOY START ====="

# =========================
# STEP 1: Move to Project
# =========================
echo "📂 Move to project"

cd "$APP_DIR"

# =========================
# STEP 2: Backup Current Commit
# =========================
echo "🛟 Backup current commit"

CURRENT_COMMIT=$(git rev-parse HEAD)

echo "Current commit: $CURRENT_COMMIT"

# =========================
# STEP 3: Git Status
# =========================
echo "📋 Git status"

git status --short || true

# =========================
# STEP 4: Pull Latest Code
# =========================
echo "📥 Pull latest code"

git fetch origin

git reset --hard "origin/$BRANCH"

# =========================
# STEP 5: Verify Frontend
# =========================
echo "🧪 Verify frontend directory"

if [ ! -d frontend ]; then
    echo "❌ frontend directory not found"
    exit 1
fi

cd frontend

if [ ! -f package.json ]; then
    echo "❌ package.json not found"
    exit 1
fi

# =========================
# STEP 6: Frontend Build
# =========================
echo "📦 Build frontend"

if [ -f package-lock.json ]; then
    npm ci
else
    npm install
fi

npm run build

cd ..

# =========================
# STEP 7: Restart Backend
# =========================
echo "🚀 Restart backend"

sudo systemctl restart "$SERVICE_NAME"

sleep 3

# =========================
# STEP 8: Health Check
# =========================
echo "🩺 Health check"

if systemctl is-active --quiet "$SERVICE_NAME"; then
    echo "✅ Backend OK"
else
    echo "❌ Backend FAILED"

    echo "🔁 Rollback start"

    git reset --hard "$CURRENT_COMMIT"

    sudo systemctl restart "$SERVICE_NAME"

    echo "✅ Rollback complete"

    exit 1
fi

# =========================
# STEP 9: Reload Nginx
# =========================
echo "🔁 Reload nginx"

sudo systemctl reload nginx

# =========================
# STEP 10: Show Service Status
# =========================
echo "📊 Service status"

systemctl status "$SERVICE_NAME" --no-pager -n 10 || true

# =========================
# DONE
# =========================
echo "🎉 ===== DEPLOY SUCCESS ====="