@echo off
rem Round 5: replicate the global env EXACTLY — kokoro+misaki with --no-deps
rem (global runs kokoro 0.7.16 with misaki 0.7.4, an off-spec but WORKING pair),
rem then the runtime deps explicitly.
setlocal
cd /d "%~dp0"
set "PY=.venv\Scripts\python.exe"
echo === no-deps kokoro/misaki === > setup_voice5.log
"%PY%" -m pip install --no-deps kokoro==0.7.16 misaki==0.7.4 >> setup_voice5.log 2>&1
echo === runtime deps === >> setup_voice5.log
"%PY%" -m pip install torch==2.10.0 scipy loguru num2words phonemizer==3.3.0 espeakng-loader==0.2.4 transformers spacy==3.8.14 >> setup_voice5.log 2>&1
"%PY%" -m pip install https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl >> setup_voice5.log 2>&1
echo === verify === >> setup_voice5.log
"%PY%" -c "import kokoro, torch; print('VENV kokoro OK, torch', torch.__version__)" >> setup_voice5.log 2>&1
echo === smoke synth === >> setup_voice5.log
"%PY%" -c "from kokoro import KPipeline; import soundfile as sf, numpy as np; p=KPipeline(lang_code='a'); chunks=[a for _,_,a in p('Quality check, one two three.', voice='af_heart', speed=1.0) if a is not None]; sf.write('kokoro_smoke.wav', np.concatenate(chunks), 24000); print('SMOKE OK')" >> setup_voice5.log 2>&1
echo ALL DONE >> setup_voice5.log
exit /b 0
