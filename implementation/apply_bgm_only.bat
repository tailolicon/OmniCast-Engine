@echo off
rem Mix ambient BGM into the finished video (one ffmpeg pass — no re-render).
rem CLOSE THE VIDEO PLAYER FIRST or the final replace will be locked.
setlocal
cd /d "%~dp0"
set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" music_lib.py "output\products\beat_glp1_nausea\20260709_0234_shot_day_dinner_what_you_eat_tonight_decides_tomor\video.mp4" health > apply_bgm.log 2>&1
exit /b %ERRORLEVEL%
