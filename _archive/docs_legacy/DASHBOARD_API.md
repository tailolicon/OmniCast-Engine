> ⚠️ **MỘT PHẦN LỖI THỜI (2026-06-18).** Phần mô tả "dashboard là HTML external builder + mock data" đã cũ — cockpit hiện tại là React app trong `frontend/` (8 tab) + desktop app `omnicast_desktop.py`, và API nay ~50 endpoint (file này liệt kê 29). Hợp đồng endpoint bên dưới vẫn dùng tham khảo được nhưng kiểm chéo với `api/server.py`. Trạng thái thật: `IMPLEMENTATION_STATUS.md`.

# OmniCast Dashboard — Real Data API

The dashboard (`OmniCast Engine (standalone).html`, built in your external AI
builder) currently ships **mock data baked in** — it does not fetch a backend.
To show **real data**, rebuild the dashboard in your builder so it fetches this
API, then run the backend.

## 1. Run the backend (real data)

```
cd implementation
python -X utf8 run_backend.py          # serves http://127.0.0.1:8767
```

CORS is open (`*`), so the dashboard can fetch it from `file://`, any localhost
port, or the builder preview.

## 2. Give your AI builder the contract

Hand it **`API_OPENAPI.json`** (OpenAPI 3.1, 29 endpoints) + this base URL:

```
BASE = http://127.0.0.1:8767
```

Tell the builder: *"Replace all mock data with fetches to BASE + these endpoints.
Poll the live ones every 2s."*

## 3. Key endpoints

| Need | Endpoint |
|------|----------|
| System KPIs / overview | `GET /api/status` |
| All channels + live status | `GET /api/channels` |
| Channel CRUD | `GET/POST/PUT/DELETE /api/channels/{id}` |
| Pipeline (active jobs + recent) | `GET /api/pipeline` |
| Niches (discovered) | `GET /api/niches` |
| Vault | `GET /api/vault` |
| Budget / spend | `GET /api/budget` |
| Errors | `GET /api/errors` |
| **Flow credits** | `GET /api/credits` → `{balance}` |
| Run pipeline phases | `POST /api/run/{id}` (niche→topic), `/script` (write), `/images` |
| **Start full video render** | `POST /api/render/{id}?script=<path>&beat_words=35` |
| **Live render status** | `GET /api/render/status` → stages, per-shot thumbnails, log, video |
| **Latest output** | `GET /api/render/latest` → `{video, thumbnail, title}` |
| Media files (mp4/png) | `GET /media/<file>` |

### `/api/render/status` shape (live render monitor)
```json
{
  "channel": "myth_greek_us", "stage": "images", "elapsed": 215.5,
  "stages": {"script":"done","storyboard":"done","images":"active",
             "compose":"pending","concat":"pending","done":"pending"},
  "shots": [{"idx":0,"heading":"...","illu":"_assets/scene_00_illu.png","state":"done"}],
  "credits": {"balance":818,"cost_per_clip":7,"needed":49},
  "video": "channel.mp4",
  "log": ["[0.0s] 7 shots...", "..."]
}
```
Thumbnails: prefix shot `illu` with `/media/` is NOT correct — illu paths are
relative to `output/real`; serve them by mounting that dir (already at `/media`
for the video). For per-shot thumbnails use `/media/_assets/scene_NN_illu.png`.

## What's real now
- Channels, pipeline, niches, vault, budget, errors, system state → real (from vault.db + channel configs + run state).
- Flow credit balance → real (live from Flow account).
- Full video render (storyboard → Flow images → Ken Burns + subtitles → concat →
  clickbait title + thumbnail) → triggered by `POST /api/render/{id}`, monitored
  by `GET /api/render/status`, output at `/media/`.

## Per-channel style
Each channel renders in its own look (set in `channels/<id>.json` `visual_style`
+ derived by `channel_render.py`): documentary / watercolor / editorial /
dark_finance, its own voice, subtitle-vs-title, and thumbnail accent colour.
