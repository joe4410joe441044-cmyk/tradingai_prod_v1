@echo off
chcp 65001 >nul

echo =========================
echo FRONT STEP START
echo =========================

echo [1] React build
cd /d C:\trading\react_dashboard
call npm run build
IF %ERRORLEVEL% NEQ 0 (
  echo ERROR: build failed
  pause
  exit /b
)

echo [2] robocopy (C -> H)
robocopy "C:\trading\react_dashboard" "H:\マイドライブ\tradingai_prod_v1\react_dashboard" /MIR /XD node_modules dist .git

IF %ERRORLEVEL% GEQ 8 (
  echo ERROR: robocopy failed
  pause
  exit /b
)

echo [3] Git push
cd /d "H:\マイドライブ\tradingai_prod_v1"

git add .
git commit -m "update UI"
git push

IF %ERRORLEVEL% NEQ 0 (
  echo ERROR: git push failed
  pause
  exit /b
)

echo =========================
echo FRONT STEP DONE
echo =========================

pause