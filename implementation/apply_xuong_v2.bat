@echo off
setlocal
cd /d "%~dp0"
echo === apply_xuong_v2 %date% %time% === > apply_xuong_v2.log

echo [1/4] py_compile server.py >> apply_xuong_v2.log
.venv\Scripts\python.exe -m py_compile src\omnicast\api\server.py >> apply_xuong_v2.log 2>&1
if errorlevel 1 (echo COMPILE FAILED >> apply_xuong_v2.log & exit /b 1)
echo compile OK >> apply_xuong_v2.log

echo [2/4] cleanup junk topics >> apply_xuong_v2.log
.venv\Scripts\python.exe cleanup_topics.py >> apply_xuong_v2.log 2>&1

echo [3/4] build frontend >> apply_xuong_v2.log
cd frontend_v2
call npm run build >> ..\apply_xuong_v2.log 2>&1
cd ..
if errorlevel 1 (echo BUILD FAILED >> apply_xuong_v2.log & exit /b 1)

echo [4/4] restart app >> apply_xuong_v2.log
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'omnicast_desktop|run_backend' } | ForEach-Object { Write-Output ('kill ' + $_.ProcessId + ' ' + $_.Name); Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }" >> apply_xuong_v2.log 2>&1
timeout /t 3 /nobreak > nul
start "" "%~dp0OmniCast.bat"
echo done >> apply_xuong_v2.log
exit /b 0
