@echo off
rem One-shot phase-2 test run (fresh process -> picks up latest code).
rem Written by Claude for the vfact prosody verification run. Safe to delete.
setlocal
cd /d "%~dp0"
set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" content_flow.py --channel beat_glp1_nausea --phase 2 --topic "Your Coffee Order Is Sabotaging Your Shot Day (Fix It in 60 Seconds)" > phase2_test_run.log 2>&1
exit /b %ERRORLEVEL%
