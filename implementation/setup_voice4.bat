@echo off
rem Round 4: clean pinned set (mirrors global working install, junk removed).
setlocal
cd /d "%~dp0"
echo === venv install clean pins === > setup_voice4.log
.venv\Scripts\python.exe -m pip install -r kokoro_pins_clean.txt >> setup_voice4.log 2>&1
echo === verify === >> setup_voice4.log
.venv\Scripts\python.exe -c "import kokoro, torch; print('VENV kokoro OK, torch', torch.__version__)" >> setup_voice4.log 2>&1
echo ALL DONE >> setup_voice4.log
exit /b 0
