@echo off
setlocal
cd /d "%~dp0frontend_v2"
call npm run build > ..\build_frontend.log 2>&1
exit /b %ERRORLEVEL%
