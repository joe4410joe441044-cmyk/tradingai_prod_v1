@echo off
chcp 65001 >nul

echo =========================
echo PROD STEP START
echo =========================

echo [4] VPS git pull
ssh joe4410joe@35.194.104.74 "cd ~/TradingAI_Bot_Prod_v1 && git pull origin main"
IF %ERRORLEVEL% NEQ 0 (
  echo ERROR: git pull failed
  pause
  exit /b
)

echo [5] dist upload
scp -r "C:\trading\react_dashboard\dist\*" joe4410joe@35.194.104.74:/home/joe4410joe/react_dashboard_dist/
IF %ERRORLEVEL% NEQ 0 (
  echo ERROR: scp failed
  pause
  exit /b
)

echo [6] VPS restart
ssh joe4410joe@35.194.104.74 "sudo systemctl restart tradingbot.service"
IF %ERRORLEVEL% NEQ 0 (
  echo ERROR: restart failed
  pause
  exit /b
)

echo =========================
echo PROD STEP DONE
echo =========================

pause