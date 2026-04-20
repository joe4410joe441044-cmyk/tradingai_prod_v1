@echo off
setlocal enabledelayedexpansion

chcp 65001 > nul

REM ==============================
REM 設定
REM ==============================
set SRC=C:\trading\tradingai_prod_v1\react_dashboard
set DEST=H:\マイドライブ\tradingai_prod_v1\react_dashboard
set GITDIR=H:\マイドライブ\tradingai_prod_v1

set VPS_USER=joe4410joe
set VPS_IP=35.194.104.74
set VPS_PATH=/home/joe4410joe/react_dashboard_dist
set VPS_PROJ=~/TradingAI_Bot_Prod_v1

set LOG=%~dp0deploy_log.txt

echo ============================== >> %LOG%
echo DEPLOY START %date% %time% >> %LOG%
echo ============================== >> %LOG%

REM ==============================
REM STEP 1: BUILD (C)
REM ==============================
echo [1/6] BUILD START
cd /d %SRC%

call npm install >> %LOG% 2>&1
IF %ERRORLEVEL% NEQ 0 (
    echo BUILD FAILED >> %LOG%
    echo ❌ npm install failed
    pause
    exit /b 1
)

call npm run build >> %LOG% 2>&1
IF %ERRORLEVEL% NEQ 0 (
    echo BUILD FAILED >> %LOG%
    echo ❌ npm run build failed
    pause
    exit /b 1
)

REM ==============================
REM STEP 2: BACKUP DIST
REM ==============================
echo [2/6] BACKUP DIST
if exist "%SRC%\backup_dist" (
    rmdir /s /q "%SRC%\backup_dist"
)
xcopy "%SRC%\dist" "%SRC%\backup_dist" /E /I /Y >> %LOG%

REM ==============================
REM STEP 3: COPY C → H
REM ==============================
echo [3/6] COPY TO H
robocopy "%SRC%" "%DEST%" /MIR /XD node_modules dist .git >> %LOG%

REM ==============================
REM STEP 4: GIT PUSH (H)
REM ==============================
echo [4/6] GIT PUSH
cd /d %GITDIR%

git add . >> %LOG% 2>&1
git commit -m "auto deploy %date% %time%" >> %LOG% 2>&1
git push origin main >> %LOG% 2>&1

IF %ERRORLEVEL% NEQ 0 (
    echo GIT FAILED >> %LOG%
    echo ❌ git push failed
    pause
    exit /b 1
)

REM ==============================
REM STEP 5: VPS DEPLOY
REM ==============================
echo [5/6] VPS DEPLOY

ssh %VPS_USER%@%VPS_IP% "cd %VPS_PROJ% && git pull origin main" >> %LOG%
IF %ERRORLEVEL% NEQ 0 (
    echo VPS GIT PULL FAILED >> %LOG%
    pause
    exit /b 1
)

scp -r "%SRC%\dist\*" %VPS_USER%@%VPS_IP%:%VPS_PATH% >> %LOG%
IF %ERRORLEVEL% NEQ 0 (
    echo SCP FAILED >> %LOG%
    pause
    exit /b 1
)

ssh %VPS_USER%@%VPS_IP% "sudo systemctl restart tradingbot.service" >> %LOG%

REM ==============================
REM STEP 6: VALIDATION + AUTO OPEN
REM ==============================
echo [6/6] VALIDATION

REM ローカル確認（開発）
start http://localhost:5173/

REM 本番確認（軽量チェック → 成功前提で開く）
curl -s http://%VPS_IP%/ >nul
IF %ERRORLEVEL% EQU 0 (
    echo VPS OK >> %LOG%
    start http://%VPS_IP%/
) ELSE (
    echo VPS NOT READY >> %LOG%
    echo ⚠ 本番URLは未オープン（失敗検知）
)

echo ============================== >> %LOG%
echo DEPLOY SUCCESS %date% %time% >> %LOG%
echo ============================== >> %LOG%

echo.
echo ✅ DEPLOY COMPLETE
echo 📄 log: %LOG%
pause