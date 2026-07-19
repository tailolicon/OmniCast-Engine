@echo off
rem Round 2: kokoro into venv with WHEELS ONLY (blis source-build broke round 1),
rem then harvest curated Incompetech BGM. Safe to delete.
setlocal
cd /d "%~dp0"
set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
echo === pip kokoro (wheels only) === > setup_voice_music2.log
"%PY%" -m pip install --only-binary=:all: kokoro espeakng-loader phonemizer >> setup_voice_music2.log 2>&1
echo === verify === >> setup_voice_music2.log
"%PY%" -c "import kokoro; print('VENV kokoro OK')" >> setup_voice_music2.log 2>&1
echo === incompetech harvest === >> setup_voice_music2.log
"%PY%" harvest_incompetech.py >> setup_voice_music2.log 2>&1
echo ALL DONE >> setup_voice_music2.log
exit /b 0
