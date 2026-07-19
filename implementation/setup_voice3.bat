@echo off
rem Round 3: mirror the EXACT working kokoro dependency pins from global Python
rem (same 3.13, wheels proven to exist) into the venv. Safe to delete.
setlocal
cd /d "%~dp0"
echo === global freeze (relevant pins) === > setup_voice3.log
python -m pip freeze | findstr /i "kokoro misaki torch spacy blis thinc num2words transformers scipy loguru phonemizer espeakng curated tokenizers safetensors regex" > kokoro_pins.txt 2>>setup_voice3.log
type kokoro_pins.txt >> setup_voice3.log
echo === venv install pinned === >> setup_voice3.log
.venv\Scripts\python.exe -m pip install --only-binary=:all: -r kokoro_pins.txt >> setup_voice3.log 2>&1
echo === verify === >> setup_voice3.log
.venv\Scripts\python.exe -c "import kokoro, torch; print('VENV kokoro OK, torch', torch.__version__)" >> setup_voice3.log 2>&1
echo === incompetech harvest === >> setup_voice3.log
.venv\Scripts\python.exe harvest_incompetech.py >> setup_voice3.log 2>&1
echo ALL DONE >> setup_voice3.log
exit /b 0
