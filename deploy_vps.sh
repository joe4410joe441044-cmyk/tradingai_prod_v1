#!/bin/bash

set -e

APP_DIR="$HOME/tradingai_prod_v1"
FRONTEND_DIR="$APP_DIR/frontend"

SERVICE_NAME="tradingai"

# 必要に応じて変更
BACKEND_URL="http://127.0.0.1:8000"
FRONTEND_URL="http://127.0.0.1"

echo "================================="
echo "🚀 TRADINGAI PRODUCTION DEPLOY"
echo "================================="

cd "$APP_DIR"

###############################################################################
# Git Information
###############################################################################

echo
echo "================================="
echo "📂 GIT INFORMATION"
echo "================================="

echo
echo "📍 Current Branch"
git branch --show-current || true

echo
echo "📌 Current Commit"
git log --oneline -1 || true

echo
echo "📋 Working Tree"
git status --short || true

echo
echo "🌐 Fetch Remote"
git fetch origin >/dev/null 2>&1 || true

echo
echo "📈 Local / Remote Status"
git status -sb || true

###############################################################################
# Frontend Build
###############################################################################

echo
echo "================================="
echo "📦 FRONTEND BUILD"
echo "================================="

cd "$FRONTEND_DIR"

npm run build

echo
echo "✅ FRONTEND BUILD SUCCESS"

cd "$APP_DIR"

###############################################################################
# Backend Restart
###############################################################################

echo
echo "================================="
echo "🚀 RESTART BACKEND"
echo "================================="

sudo systemctl restart "$SERVICE_NAME"

sleep 5

echo
echo "✅ BACKEND RESTARTED"

###############################################################################
# Reload Nginx
###############################################################################

echo
echo "================================="
echo "🌐 RELOAD NGINX"
echo "================================="

sudo systemctl reload nginx

echo
echo "✅ NGINX RELOADED"

###############################################################################
# Service Health
###############################################################################

echo
echo "================================="
echo "🩺 SERVICE STATUS"
echo "================================="

echo
echo "[Backend]"
systemctl status "$SERVICE_NAME" \
    --no-pager \
    -n 10

echo
echo "[Nginx]"
systemctl status nginx \
    --no-pager \
    -n 10

###############################################################################
# API Health Check
###############################################################################

echo
echo "================================="
echo "🩺 API HEALTH CHECK"
echo "================================="

echo
echo "[Backend Root]"

if curl -fsS "$BACKEND_URL/" >/dev/null; then
    echo "✅ Backend Root OK"
else
    echo "❌ Backend Root FAILED"
    exit 1
fi

echo
echo "[Health Endpoint]"

if curl -fsS "$BACKEND_URL/health" >/dev/null; then
    echo "✅ Health API OK"
else
    echo "⚠️  /health endpoint not available"
fi

echo
echo "[Runtime API]"

if curl -fsS "$BACKEND_URL/api/runtime" >/dev/null; then
    echo "✅ Runtime API OK"
else
    echo "⚠️  Runtime API not available"
fi

###############################################################################
# Frontend Check
###############################################################################

echo
echo "================================="
echo "🌐 FRONTEND CHECK"
echo "================================="

if curl -fsS "$FRONTEND_URL" >/dev/null; then
    echo "✅ Frontend OK"
else
    echo "⚠️  Frontend check failed"
fi

###############################################################################
# Deploy Summary
###############################################################################

echo
echo "================================="
echo "📌 DEPLOY SUMMARY"
echo "================================="

echo
echo "Branch:"
git branch --show-current || true

echo
echo "Commit:"
git log --oneline -1 || true

echo
echo "Git Status:"
git status -sb || true

echo
echo "================================="
echo "🎉 DEPLOY SUCCESS"
echo "================================="