@echo off
rem 1) Find where kokoro lives (global vs venv). 2) Harvest royalty-free BGM
rem from competitor credits into assets/music/. Safe to delete.
setlocal
cd /d "%~dp0"
echo === GLOBAL python === > diag_kokoro.log
python -c "import sys; print(sys.executable)" >> diag_kokoro.log 2>&1
python -m pip show kokoro >> diag_kokoro.log 2>&1
python -c "import kokoro, torch; print('GLOBAL OK: kokoro', kokoro.__version__ if hasattr(kokoro,'__version__') else '?', '| torch', torch.__version__)" >> diag_kokoro.log 2>&1
echo === VENV python === >> diag_kokoro.log
.venv\Scripts\python.exe -m pip show kokoro >> diag_kokoro.log 2>&1
.venv\Scripts\python.exe -c "import kokoro; print('VENV OK')" >> diag_kokoro.log 2>&1
echo === music harvester === >> diag_kokoro.log
.venv\Scripts\python.exe music_harvester.py >> music_harvest.log 2>&1
echo done >> diag_kokoro.log
exit /b 0
