#!/bin/bash

set -e

APP_DIR="$HOME/tradingai_prod_v1"
SERVICE_NAME="tradingai"

echo "================================="
echo "🚀 TRADINGAI DEPLOY START"
echo "================================="

cd "$APP_DIR"

echo ""
echo "📋 GIT STATUS"
git status --short || true

echo ""
echo "================================="
echo "📦 FRONTEND BUILD"
echo "================================="

cd frontend

npm run build

echo ""
echo "✅ FRONTEND BUILD SUCCESS"

cd ..

echo ""
echo "================================="
echo "🚀 RESTART BACKEND"
echo "================================="

sudo systemctl restart "$SERVICE_NAME"

sleep 3

echo ""
echo "✅ BACKEND RESTARTED"

echo ""
echo "================================="
echo "🌐 RELOAD NGINX"
echo "================================="

sudo systemctl reload nginx

echo ""
echo "✅ NGINX RELOADED"

echo ""
echo "================================="
echo "🩺 BACKEND HEALTH CHECK"
echo "================================="

systemctl status "$SERVICE_NAME" \
  --no-pager -n 10

echo ""
echo "================================="
echo "🩺 NGINX HEALTH CHECK"
echo "================================="

systemctl status nginx \
  --no-pager -n 10

echo ""
echo "================================="
echo "🎉 DEPLOY SUCCESS"
echo "================================="