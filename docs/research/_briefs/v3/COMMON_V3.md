# COMMON CONTEXT V3 — Chinese Video Translation Stack for OmniCast Engine

## Who is asking

OmniCast Engine (`E:\Project\OmniCast Engine`) is a Python 24/7 YouTube video production
system. Package root: `implementation/src/omnicast/` with existing subpackages
`media/` (tts.py, voice_router.py, subtitle.py, ffmpeg.py, render_engine.py, providers/),
`agents/`, `pipeline/`, `vault/` (SQLite `output/vault.db` = single source of truth),
`api/` (FastAPI), `storage/products.py` (one folder per video).

We are adding a new capability: **download Chinese (Douyin) videos and republish them
translated into Vietnamese** — download → ASR (zh) → translate zh→vi → subtitle → TTS dub →
mix → export. The owner does NOT speak Chinese, so translation quality and QC gating are
the highest-value parts.

## Hard rule for this research

**We are NOT inventing mechanisms. We are harvesting existing, proven ones.**
Your job is to extract EVERYTHING that is hard-won tuning knowledge and cannot be guessed:
exact endpoints, exact headers, exact numeric thresholds, exact prompt text, exact retry
policies, exact ffmpeg filter strings, exact model names, exact schema fields.

## Output requirements (STRICT)

1. Write the report to the exact path given in your brief. One file. Markdown.
2. **VERBATIM + CITATION.** Every extracted constant, prompt, header dict, endpoint, or
   filter string must be quoted verbatim in a fenced code block, immediately followed by
   `-> <relative/path/to/file.py>:<line>`. A claim without a file:line citation is worthless.
3. Do NOT summarize prompts or config into prose. Copy them exactly, including whitespace.
4. If a value is computed rather than literal, show the computing code verbatim.
5. Prefer completeness over commentary. Minimal prose. No praise, no filler, no "in
   conclusion". Do not restate the brief back to us.
6. If something asked for does not exist in the repo, write one line:
   `NOT FOUND: <thing>` — do not speculate or invent.
7. Chinese-language identifiers, comments, and error strings: keep the original Chinese,
   add a short English gloss in parentheses.

## Report skeleton to follow

```
# <title>
## 0. TL;DR — what to port, ranked
## 1. <per-repo or per-subsystem sections as specified in the brief>
## N. PORT PLAN FOR OMNICAST
   - table: capability | source repo | source file:line | license | port difficulty | note
## N+1. TRAPS / GOTCHAS
   - things that will silently break (anti-bot, encoding, timing, rate limits, cache keys)
## N+2. NOT FOUND
```

## License awareness (must be respected in the PORT PLAN section)

- `douyin-downloader` = MIT -> free to copy.
- `Douyin_TikTok_Download_API`, `f2` = Apache-2.0 -> copy with attribution + NOTICE.
- `TikTokDownloader` = **GPL-3.0** -> DO NOT recommend copying source into OmniCast.
  For this repo, describe the *technique/algorithm* and recommend clean-room reimplementation
  or out-of-process invocation. Flag every GPL-sourced item explicitly.
- `Tool_Reup_Douyin` = no LICENSE file, but the project owner has confirmed it is a community
  repo and cleared direct reuse. Treat it as **free to copy verbatim**: the port plan should
  say which files/functions to lift as-is, which to adapt, and which to drop.

## Budget

Be fast and cheap. Do not run web searches. Do not spawn subagents. Read files directly.
