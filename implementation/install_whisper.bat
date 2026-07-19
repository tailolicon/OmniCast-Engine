@echo off
setlocal
cd /d "%~dp0"
.venv\Scripts\python.exe -m pip install faster-whisper > install_whisper.log 2>&1
.venv\Scripts\python.exe -c "import faster_whisper; print('faster-whisper OK')" >> install_whisper.log 2>&1
exit /b 0
