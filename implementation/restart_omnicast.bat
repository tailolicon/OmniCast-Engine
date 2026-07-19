@echo off
setlocal
cd /d "%~dp0"
echo [restart] killing old omnicast processes... > restart_omnicast.log
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'omnicast_desktop|run_backend' } | ForEach-Object { Write-Output ('kill ' + $_.ProcessId + ' ' + $_.Name); Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }" >> restart_omnicast.log 2>&1
timeout /t 3 /nobreak > nul
echo [restart] relaunching OmniCast... >> restart_omnicast.log
start "" "%~dp0OmniCast.bat"
echo [restart] done >> restart_omnicast.log
exit /b 0
