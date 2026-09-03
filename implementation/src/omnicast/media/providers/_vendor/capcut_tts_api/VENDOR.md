# Vendored: K07VN/capcut-tts-api

Source: https://github.com/K07VN/capcut-tts-api (MIT)

## What we changed vs upstream

1. **Import rebinding** — `capcut_tts_api.*` → `omnicast.media.providers._vendor.capcut_tts_api.*`
2. **Voice.json path** — shipped under `data/Voice.json` (not package parent)
3. **TTS status poll** — CapCut SG API returns `status: "succeed"` (not `"success"`); both accepted
4. **STT status poll** — same `succeed` acceptance

## Refresh from upstream

```text
git clone https://github.com/K07VN/capcut-tts-api _refs/capcut-tts-api
# copy *.py + Voice.json, re-apply import rebinding + status patch
```

Do **not** import this package from application code — use `omnicast.media.providers.tts_capcut`.
