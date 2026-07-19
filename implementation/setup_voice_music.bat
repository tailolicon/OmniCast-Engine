@echo off
rem 1) Install kokoro (+espeak deps) into the venv so the channel's main voice
rem    actually runs (it lives only in global Python today).
rem 2) Harvest CC0 BGM from FreePD into assets/music/ per mood.
rem Safe to delete after use.
setlocal
cd /d "%~dp0"
set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
echo === pip kokoro === > setup_voice_music.log
"%PY%" -m pip install kokoro soundfile espeakng-loader phonemizer >> setup_voice_music.log 2>&1
echo === verify === >> setup_voice_music.log
"%PY%" -c "import kokoro, soundfile; print('VENV kokoro OK')" >> setup_voice_music.log 2>&1
echo === freepd harvest === >> setup_voice_music.log
"%PY%" harvest_freepd.py >> setup_voice_music.log 2>&1
echo ALL DONE >> setup_voice_music.log
exit /b 0
