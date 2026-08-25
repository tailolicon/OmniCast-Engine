# BRIEF D1 — Douyin/TikTok download layer: full mechanism + config extraction

Read `docs/research/_briefs/v3/COMMON_V3.md` first and obey its output rules.

**Working root:** `E:\Project\OmniCast Engine\_refs`
**Write report to:** `E:\Project\OmniCast Engine\docs\research\V3_D1_DouyinDownload.md`

## Repos in scope (read all four, compare them)

1. `_refs/Douyin_TikTok_Download_API` (Apache-2.0) — FastAPI service, `crawlers/`, `config.yaml`
2. `_refs/f2` (Apache-2.0) — async library+CLI, `f2/apps/douyin/`
3. `_refs/TikTokDownloader` (GPL-3.0) — `src/`, has `encipher_example.py`
4. `_refs/douyin-downloader` (MIT) — `core/`, `auth/`, `config/`, `config.example.yml`

## What we need — answer ALL of these, per repo, with file:line

### A. Anti-bot signature (the single most important thing)
Douyin requires request signing. For each repo:
- Which signature params are produced? (`a_bogus`, `X-Bogus`, `msToken`, `ttwid`, `verifyFp`,
  `s_v_web_id`, `_signature`, `mas`, `X-Gnarly`, ...). Give the exact param name list per endpoint.
- Where is each one generated? Give file:line and paste the core function verbatim.
- Is it pure Python, JS-via-execjs/node, WASM, or a remote service? Paste the loader code.
- Paste any embedded JS/WASM filenames and their paths.
- `msToken`: how is it obtained (fake/random-generated vs fetched from an endpoint)? Paste the
  generator and any fixed-length constants.
- `ttwid`/`verifyFp`: how obtained? Paste the code and any hardcoded seed strings.
- Which repo has the most current/maintained signature implementation? Justify with dates
  from CHANGELOG / git-visible version strings.

### B. Endpoints
Produce ONE consolidated table of every Douyin API endpoint used across the four repos:
`purpose | full URL path | HTTP method | required query params | required headers | which repo | file:line`
Cover at minimum: single video detail (aweme detail), share/short-link resolution (`v.douyin.com`),
user post list, user profile, collection/mix (合集), music, live, search, comments.
Also note the **web vs mobile/app API** distinction if both are present.

### C. Headers, cookies, UA
- Paste the exact default headers dict(s) verbatim, per repo.
- Paste the exact default `User-Agent` strings.
- Which cookies are REQUIRED vs optional? Is login/`sessionid` needed for plain public video
  download? Paste the cookie handling code and any cookie validation/parse helpers.
- Any browser-cookie import feature (e.g. `chrome-cookie-sniffer` dir in repo 1)? Explain how it works.

### D. No-watermark video URL derivation
This is the core value. For each repo:
- Paste verbatim the code that picks the download URL from the aweme JSON.
- Exact JSON key paths tried, in order (e.g. `video.play_addr.url_list`, `video.bit_rate[*]`,
  `video.download_addr`, `play_addr_h264`, `video.play_addr_265`...).
- Any URL string rewriting (e.g. `playwm` -> `play`, domain swap, `ratio=` param, `media_type`)?
  Paste exact string replacements.
- How is the **highest bitrate / best quality** variant selected? Paste the comparison code and
  the fields used (`bit_rate`, `quality_type`, `gear_name`, `FPS`, `is_h265`). List the exact
  `gear_name`/`quality_type` values seen and their ranking.
- How are image-post ("图集"/slideshow) and live-photo aweme types handled?
- Audio/music extraction: exact key path and format.

### E. Download transport
- Chunked download config: chunk size bytes, timeout seconds, connect timeout, retry count,
  backoff formula, max concurrent downloads/semaphore size. Paste the config verbatim.
- Resume/range-request support? Paste it.
- Proxy config shape. Paste it.
- Rate limiting / sleep-between-requests values. Paste exact numbers.
- Progress reporting mechanism.

### F. Config files, fully dumped
- Paste `_refs/Douyin_TikTok_Download_API/config.yaml` verbatim, in full.
- Paste `_refs/douyin-downloader/config.example.yml` verbatim, in full.
- Paste f2's default app config (find the douyin conf.yaml / defaults) verbatim, in full.
- Paste TikTokDownloader's settings/defaults structure verbatim.
- For each: annotate every field with what it actually controls (trace to the code that reads it).

### G. Error handling & failure modes
- Exact error/response codes handled (`status_code`, `status_msg`) and their meanings.
- What happens on: expired cookie, rate limit / risk-control ("滑块"/captcha/verify page),
  region block, deleted video, private account. Paste the detection code.
- Any retry-with-new-signature logic? Paste it.

### H. Batch / monitoring features worth stealing
- Account/user "watch for new posts" implementations, incremental download bookkeeping
  (how do they remember what was already downloaded — DB? sqlite? json?). Paste the schema.
- Filters (by date, by like count, by duration).
- Metadata sidecar output format (what fields get saved next to the video). Paste the writer.

### I. Which one should OmniCast actually use?
Pick ONE primary + ONE fallback. Decide on: license, maintenance recency, Python-only vs
node dependency, async support, ease of embedding as a library (not a CLI/service).
Give a concrete "wire it in" sketch: the 3-6 functions/classes we would call, with their
import paths and signatures pasted verbatim.

## Reminders

- No web search. No subagents. Read files.
- Every number, header, URL, and key path must be verbatim + `file:line`.
- Mark GPL-3.0 items from `TikTokDownloader` explicitly as describe-only.
