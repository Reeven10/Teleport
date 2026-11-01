@echo off
rem Double-click to start Teleport on this Windows laptop. The first run installs it (a few minutes).
title Teleport
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo First start: installing Teleport. This takes a few minutes...
  where python >nul 2>nul || (
    echo Python 3.11 or newer is needed: install it from https://www.python.org/downloads/ and tick "Add to PATH".
    pause
    exit /b 1
  )
  python -m venv .venv || goto :failed
  ".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
  ".venv\Scripts\python.exe" -m pip install -e agent || goto :failed
)

if not exist "ui\dist\index.html" (
  where npm >nul 2>nul || (
    echo Node.js is needed once to build the dashboard: install it from https://nodejs.org/ and start again.
    pause
    exit /b 1
  )
  echo Building the dashboard...
  call npm install || goto :failed
  call npm run build || goto :failed
)

".venv\Scripts\python.exe" -m teleport.launch %*
pause
exit /b 0

:failed
echo.
echo Teleport could not be installed. See the messages above.
pause
exit /b 1
