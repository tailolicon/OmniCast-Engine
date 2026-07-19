@echo off
cd /d "%~dp0"
echo === %date% %time% === > check_backend.log
curl -s -m 10 -o nul -w "webui index: HTTP %%{http_code}\n" http://127.0.0.1:8767/ >> check_backend.log 2>&1
curl -s -m 10 -o nul -w "new bundle: HTTP %%{http_code}\n" http://127.0.0.1:8767/assets/index-DRL826G3.js >> check_backend.log 2>&1
curl -s -m 10 http://127.0.0.1:8767/api/topics/beat_glp1_nausea >> check_backend.log 2>&1
echo. >> check_backend.log
curl -s -m 10 "http://127.0.0.1:8767/api/dedup/check?channel_id=beat_glp1_nausea&title=test%%20topic" >> check_backend.log 2>&1
exit /b 0
