@echo off
rem Render the Shot Day Dinner product (all-stock, prosody sidecar). Safe to delete.
setlocal
cd /d "%~dp0"
set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
set "P=output\products\beat_glp1_nausea\20260709_0234_shot_day_dinner_what_you_eat_tonight_decides_tomor"
"%PY%" -X utf8 render_real_video.py --script "%P%\script.txt" --channel beat_glp1_nausea --beat-words 12 --subtitles --all-stock --out "%P%\video.mp4" > phase3_render.log 2>&1
exit /b %ERRORLEVEL%
