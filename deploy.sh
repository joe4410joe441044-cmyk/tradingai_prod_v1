cd ~/TradingAI_Bot_Prod_v1

echo "=== STEP 1: pull latest code ==="
git pull origin main

echo "=== STEP 2: React build ==="
cd react_dashboard

# 依存が安定している前提なら ci 推奨（なければ install）
if [ -f package-lock.json ]; then
  npm ci
else
  npm install
fi

npm run build

cd ..

echo "=== STEP 3: restart service ==="
sudo systemctl restart tradingbot.service

echo "=== DEPLOY DONE ==="