@echo off

REM ==============================
REM UTF-8設定（文字化け対策）
REM ==============================
chcp 65001 > nul

REM ==============================
REM 設定
REM ==============================
set SRC=C:\trading\react_dashboard
set DEST=H:\マイドライブ\tradingai_prod_v1\react_dashboard

REM ==============================
REM Build
REM ==============================
echo [1/3] Build start...
cd /d %SRC%
call npm run build

REM ==============================
REM Copy (robocopy)
REM ==============================
echo [2/3] Copy files...
robocopy "%SRC%" "%DEST%" /MIR /XD node_modules dist .git

REM ==============================
REM Git Push
REM ==============================
echo [3/3] Git push...
cd /d H:\マイドライブ\tradingai_prod_v1

git add .
git commit -m "auto deploy"
git push

echo.
echo ✅ Deploy Complete
pause