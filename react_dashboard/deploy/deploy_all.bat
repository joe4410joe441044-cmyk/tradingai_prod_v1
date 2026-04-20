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
REM STEP 1: Build (C)
REM ==============================
echo [1/5] BUILD START
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
REM STEP 2: Backup dist (ロールバック用)
REM ==============================
echo [2/5] BACKUP DIST
if exist backup_dist (
    rmdir /s /q backup_dist
)
xcopy "%SRC%\dist" "%SRC%\backup_dist" /E /I /Y >> %LOG%

REM ==============================
REM STEP 3: Copy C → H
REM ==============================
echo [3/5] COPY TO H
robocopy "%SRC%" "%DEST%" /MIR /XD node_modules dist .git >> %LOG%

REM ==============================
REM STEP 4: Git Push (H only)
REM ==============================
echo [4/5] GIT PUSH
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
REM STEP 5: VPS deploy
REM ==============================
echo [5/5] VPS DEPLOY

ssh %VPS_USER%@%VPS_IP% "cd %VPS_PROJ% && git pull origin main" >> %LOG%
IF %ERRORLEVEL% NEQ 0 (
    echo VPS GIT PULL FAILED >> %LOG%
    echo ❌ VPS git pull failed
    pause
    exit /b 1
)

scp -r "%SRC%\dist\*" %VPS_USER%@%VPS_IP%:%VPS_PATH% >> %LOG%
IF %ERRORLEVEL% NEQ 0 (
    echo SCP FAILED >> %LOG%
    echo ❌ scp failed
    pause
    exit /b 1
)

ssh %VPS_USER%@%VPS_IP% "sudo systemctl restart tradingbot.service" >> %LOG%
IF %ERRORLEVEL% NEQ 0 (
    echo RESTART FAILED >> %LOG%
    echo ❌ restart failed
    pause
    exit /b 1
)

echo ============================== >> %LOG%
echo DEPLOY SUCCESS %date% %time% >> %LOG%
echo ============================== >> %LOG%

echo.
echo ✅ DEPLOY COMPLETE
echo 📄 log: %LOG%
pause