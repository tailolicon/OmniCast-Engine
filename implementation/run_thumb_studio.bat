@echo off
setlocal
cd /d "%~dp0"
set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" -X utf8 thumb_studio.py generate "output\products\beat_glp1_nausea\20260709_0234_shot_day_dinner_what_you_eat_tonight_decides_tomor" --count 1 --per-angle 4 > thumb_studio.log 2>&1
exit /b %ERRORLEVEL%
