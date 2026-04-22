@echo off
setlocal enabledelayedexpansion

chcp 65001 > nul

REM ==============================
REM 設定
REM ==============================
set SRC=C:\trading\tradingai_prod_v1\react_dashboard

set VPS_USER=joe4410joe
set VPS_IP=35.194.104.74
set VPS_PATH=/home/joe4410joe/TradingAI_Bot_Prod_v1/react_dashboard_dist

set LOG=%~dp0deploy_log.txt

echo ============================== >> %LOG%
echo DEPLOY START %date% %time% >> %LOG%
echo ============================== >> %LOG%

REM ==============================
REM STEP 1: BUILD
REM ==============================
echo [1/4] BUILD START
cd /d %SRC%

call npm install >> %LOG% 2>&1
IF ERRORLEVEL 1 (
    echo BUILD FAILED (npm install) >> %LOG%
    echo ❌ npm install failed
    exit /b 1
)

call npm run build >> %LOG% 2>&1
IF ERRORLEVEL 1 (
    echo BUILD FAILED (npm run build) >> %LOG%
    echo ❌ npm run build failed
    exit /b 1
)

IF NOT EXIST "%SRC%\dist\index.html" (
    echo DIST NOT FOUND >> %LOG%
    echo ❌ build output missing
    exit /b 1
)

REM ==============================
REM STEP 2: BACKUP
REM ==============================
echo [2/4] BACKUP DIST

if exist "%SRC%\backup_dist" (
    rmdir /s /q "%SRC%\backup_dist"
)

xcopy "%SRC%\dist" "%SRC%\backup_dist" /E /I /Y >> %LOG%

REM ==============================
REM STEP 3: VPS UPLOAD
REM ==============================
echo [3/4] VPS DEPLOY

ssh %VPS_USER%@%VPS_IP% "mkdir -p %VPS_PATH%" >> %LOG%

scp -r "%SRC%\dist\*" %VPS_USER%@%VPS_IP%:%VPS_PATH% >> %LOG%
IF ERRORLEVEL 1 (
    echo SCP FAILED >> %LOG%
    echo ❌ file transfer failed
    exit /b 1
)

ssh %VPS_USER%@%VPS_IP% "ls %VPS_PATH%/index.html" >> %LOG%
IF ERRORLEVEL 1 (
    echo DIST NOT FOUND ON VPS >> %LOG%
    exit /b 1
)

REM ==============================
REM STEP 4: RESTART SERVICE
REM ==============================
echo [4/4] RESTART SERVICE

ssh %VPS_USER%@%VPS_IP% "sudo systemctl restart tradingbot.service" >> %LOG%

echo ============================== >> %LOG%
echo DEPLOY SUCCESS %date% %time% >> %LOG%
echo ============================== >> %LOG%

echo.
echo ✅ DEPLOY COMPLETE
echo 📄 log: %LOG%