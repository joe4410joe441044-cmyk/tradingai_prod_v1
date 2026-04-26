@echo off
setlocal enabledelayedexpansion

chcp 65001 > nul

REM ==============================
REM 固定パス（重要：絶対ブレさせない）
REM ==============================
set ROOT=C:\trading\tradingai_prod_v1
set SRC=%ROOT%\react_dashboard

set VPS_USER=joe4410joe
set VPS_IP=35.194.104.74
set VPS_PATH=/home/joe4410joe/TradingAI_Bot_Prod_v1/react_dashboard_dist

set LOG=%~dp0deploy_log.txt

echo ============================== >> %LOG%
echo DEPLOY START %date% %time% >> %LOG%
echo ============================== >> %LOG%

REM ==============================
REM STEP 1: BUILD（必ずROOT基準）
REM ==============================
echo [1/4] BUILD START >> %LOG%

cd /d %SRC% >> %LOG%

echo CURRENT DIR: >> %LOG%
cd >> %LOG%

REM node_modulesチェック
if not exist node_modules (
    call npm install >> %LOG% 2>&1
    IF ERRORLEVEL 1 (
        echo ❌ npm install failed >> %LOG%
        exit /b 1
    )
)

REM build実行
call npm run build >> %LOG% 2>&1
IF ERRORLEVEL 1 (
    echo ❌ npm run build failed >> %LOG%
    type %LOG%
    exit /b 1
)

REM dist確認
IF NOT EXIST "%SRC%\dist\index.html" (
    echo ❌ DIST NOT FOUND >> %LOG%
    exit /b 1
)

REM ==============================
REM STEP 2: BACKUP
REM ==============================
echo [2/4] BACKUP DIST >> %LOG%

set BACKUP=%SRC%\backup_dist_%date:~0,4%%date:~5,2%%date:~8,2%

if exist "%BACKUP%" (
    rmdir /s /q "%BACKUP%"
)

xcopy "%SRC%\dist" "%BACKUP%" /E /I /Y >> %LOG%

REM ==============================
REM STEP 3: VPS UPLOAD
REM ==============================
echo [3/4] VPS DEPLOY >> %LOG%

ssh %VPS_USER%@%VPS_IP% "mkdir -p %VPS_PATH%" >> %LOG%

scp -r "%SRC%\dist\." %VPS_USER%@%VPS_IP%:%VPS_PATH% >> %LOG%
IF ERRORLEVEL 1 (
    echo ❌ SCP FAILED >> %LOG%
    exit /b 1
)

ssh %VPS_USER%@%VPS_IP% "ls %VPS_PATH%/index.html" >> %LOG%
IF ERRORLEVEL 1 (
    echo ❌ DIST NOT FOUND ON VPS >> %LOG%
    exit /b 1
)

REM ==============================
REM STEP 4: RESTART SERVICE
REM ==============================
echo [4/4] RESTART SERVICE >> %LOG%

ssh %VPS_USER%@%VPS_IP% "sudo systemctl restart tradingbot.service" >> %LOG%
IF ERRORLEVEL 1 (
    echo ❌ SERVICE RESTART FAILED >> %LOG%
    exit /b 1
)

echo ============================== >> %LOG%
echo DEPLOY SUCCESS %date% %time% >> %LOG%
echo ============================== >> %LOG%

echo.
echo ✅ DEPLOY COMPLETE
echo 📄 log: %LOG%