@echo off
setlocal
cd /d "%~dp0"
set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" -X utf8 make_thumb_flow.py > make_thumb_flow.log 2>&1
exit /b %ERRORLEVEL%
