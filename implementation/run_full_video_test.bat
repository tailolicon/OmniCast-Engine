@echo off
rem Full acceptance run: script (claude_first, all fixes) -> render -> output audit.
rem FLOW_SKIP=1: all-stock visuals — no Flow browser automation, safe to run while
rem the machine is in use (gaming). Written by Claude; safe to delete.
setlocal
cd /d "%~dp0"
set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
set "FLOW_SKIP=1"
"%PY%" content_flow.py --channel beat_glp1_nausea --phase 3 --topic "Shot Day Dinner: What You Eat Tonight Decides Tomorrow's Nausea" > phase3_full_video.log 2>&1
exit /b %ERRORLEVEL%
