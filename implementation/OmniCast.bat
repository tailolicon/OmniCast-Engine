@echo off
setlocal
cd /d "%~dp0"

set "PYW=.venv\Scripts\pythonw.exe"
set "PY=.venv\Scripts\python.exe"

if exist "%PYW%" (
  start "" "%PYW%" omnicast_desktop.py
  exit /b 0
)

if exist "%PY%" (
  start "" "%PY%" omnicast_desktop.py
  exit /b 0
)

where pythonw >nul 2>nul
if %ERRORLEVEL% EQU 0 (
  start "" pythonw omnicast_desktop.py
  exit /b 0
)

where python >nul 2>nul
if %ERRORLEVEL% EQU 0 (
  start "" python omnicast_desktop.py
  exit /b 0
)

echo [ERROR] Python not found.
echo Install Python or create the project venv in the implementation folder:
echo   cd implementation
echo   uv venv ^& uv sync
pause
exit /b 1
