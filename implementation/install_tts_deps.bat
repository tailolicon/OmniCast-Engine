@echo off
rem Install missing TTS deps into the project venv (edge-tts + soundfile).
rem The venv was rebuilt at some point without them -> render TTS failed.
setlocal
cd /d "%~dp0"
set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" -m pip install edge-tts soundfile > install_tts_deps.log 2>&1
exit /b %ERRORLEVEL%
