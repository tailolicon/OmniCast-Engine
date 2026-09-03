"""Learn from competitors' breakout videos — HOW winners name titles, design
thumbnails and structure scripts — and distill reusable playbooks per niche.

WHAT CHANGED (strategic review §4.1/§4.8, P0 items 1 and 3)

This module used to take `sort(views)[:12]`. That answers "what do high-view
videos look like", which is not "what made this video win":

  * absolute views favour BIG channels over the small channel that genuinely
    broke out, and OLD videos that merely accumulated views;
  * with no control group, every trait shared by the winners looks like a cause.
    Most of them are just the channel's house style — present in its flops too.
    That is textbook survivorship bias, and it was being written straight into
    the title/thumbnail/script generators.

So the input is now a COHORT from `analytics.cohort`: per-channel median
outliers (winners) each paired with an ordinary sibling video from the SAME
channel, close in publish date and similar in length (controls). Every prompt
below is a CONTRAST prompt — a pattern earns a place in a playbook only when it
separates the two groups. When no controls could be matched, the playbook is
still produced but is stamped UNCONTROLLED so downstream readers discount it
instead of trusting it equally.

Transcripts now come from `analytics.transcript`: full text (previously cut at
3,500 characters, i.e. the opening act stood in for the whole video) with an ASR
fallback for channels that publish no captions.

Pipeline:
  1. Scan competitor handles (reuse YouTubeScanner) → recent videos per channel.
  2. select_cohort → winners + matched controls.
  3. title_playbook  ← DeepSeek contrasts winner vs control titles.
  4. thumbnail_playbook ← Gemini/Claude vision contrasts winner vs control thumbs.
  5. script_playbook ← per-video digests of FULL transcripts, then a contrast
     synthesis across the two groups.
  6. Persist to vault.competitor_intel (keyed by niche) → fed into the title +
     thumbnail generators (clickbait.py).

Best-effort: needs youtube_api_key + competitor handles + (vision) GOOGLE_API_KEY.
Skips gracefully when missing.
"""

from __future__ import annotations

import asyncio
import atexit
import json
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import structlog

from omnicast.analytics.cohort import Cohort, select_cohort
from omnicast.analytics.transcript import Transcript, fetch_transcript

logger = structlog.get_logger()

# How many videos to pull per competitor channel before cohort selection. The
# channel median is only as honest as the sample it is computed over.
VIDEOS_PER_CHANNEL = 30
# Winners carried into the (expensive) transcript stage.
SCRIPT_SAMPLE_WINNERS = 4
# Per-video transcript digest budget. A 20-minute video is ~2 chunks; the cap
# stops one three-hour VOD from eating a whole learning run.
MAX_CHUNKS_PER_VIDEO = 4
TRANSCRIPT_CHUNK_CHARS = 12_000

# Thumbnail fetching: a per-socket timeout is not a deadline. A server dripping
# one byte every two seconds kept a single urlopen alive for 40s at timeout=15,
# and there are up to ten of them per run.
THUMB_TOTAL_DEADLINE_SECONDS = 45.0
THUMB_SOCKET_TIMEOUT = 10
THUMB_MAX_BYTES = 4 * 1024 * 1024
# Vision SDK ceilings. google-genai defaults to no timeout at all; anthropic
# defaults to 600s. Either one can pin a worker thread for the whole run.
VISION_TIMEOUT_SECONDS = 90

# Transcript and ASR run on their OWN small pool, not the default executor.
# asyncio's default is min(32, cpu+4) threads shared by every `to_thread` caller
# in the process; one 45-minute ASR job per worker starved unrelated 10ms calls
# for seconds at a time. Bounding it here also caps how many Whisper models can
# be resident at once.
RESEARCH_POOL_SIZE = 2
# A ThreadPoolExecutor queue is unbounded. Two threads plus an unbounded queue
# is not backpressure — it is an invisible hours-long backlog behind an HTTP
# request nobody can cancel. This caps how much work may be in flight at once
# and rejects the rest with a reason the caller can record.
MAX_RESEARCH_IN_FLIGHT = RESEARCH_POOL_SIZE * 4
_RESEARCH_EXECUTOR = ThreadPoolExecutor(
    max_workers=RESEARCH_POOL_SIZE, thread_name_prefix="omnicast-research")
_research_in_flight = 0


class ResearchPoolBusy(RuntimeError):
    """Raised instead of silently queueing behind a multi-hour backlog."""


@atexit.register
def _shutdown_research_pool() -> None:
    # Non-daemon worker threads make interpreter exit block on an unbounded
    # join: a SIGTERM to a worker mid-ASR hung for the whole ASR duration and
    # then got SIGKILLed.
    _RESEARCH_EXECUTOR.shutdown(wait=False, cancel_futures=True)


async def _in_research_pool(func, *args, **kwargs):
    """Run a long blocking research job off the loop AND off the shared pool."""
    global _research_in_flight
    if _research_in_flight >= MAX_RESEARCH_IN_FLIGHT:
        raise ResearchPoolBusy(
            f"{_research_in_flight} research jobs already in flight "
            f"(limit {MAX_RESEARCH_IN_FLIGHT}); refusing to queue another")
    loop = asyncio.get_running_loop()
    if kwargs:
        from functools import partial

        func = partial(func, **kwargs)
    _research_in_flight += 1
    try:
        return await loop.run_in_executor(_RESEARCH_EXECUTOR, func, *args)
    finally:
        _research_in_flight -= 1

# Prepended to any playbook learned without a control group. The reader — human
# or the writer agent — must be able to see that this is an observation, not a
# finding.
UNCONTROLLED_STAMP = (
    "[UNCONTROLLED — no matched control videos could be paired with these "
    "winners, so nothing below is verified to separate winners from the "
    "channel's ordinary output. Treat as a hypothesis, not a rule.]\n\n"
)

# P0.1 group 2: the cohort can now be controlled for SOME winners and not
# others, and "1 of 12 controlled" used to render identically to "12 of 12".
# A separate stamp exists because collapsing partial into either extreme is a
# lie in one direction or the other.
PARTIAL_CONTROL_STAMP_TEMPLATE = (
    "[PARTIALLY CONTROLLED — {matched} of {total} winners had a matched control "
    "video; the remaining {unmatched} contributed uncontrolled observations. "
    "Differences stated below are verified only on the matched pairs.]\n\n"
)


def _partial_stamp(cohort: Cohort) -> str:
    return PARTIAL_CONTROL_STAMP_TEMPLATE.format(
        matched=len(cohort.matched_winners),
        total=len(cohort.winners),
        unmatched=len(cohort.unmatched_winners),
    )

_CONTRAST_RULE = (
    "You are given two groups from the SAME channels: WINNERS (videos that beat "
    "their own channel's median by >=2x) and CONTROLS (ordinary videos from the "
    "same channel, published near the same time, similar length). Report ONLY "
    "what SEPARATES the groups. If a trait appears in both groups, it is that "
    "channel's house style, not a cause of winning — either omit it or label it "
    "explicitly as 'house style (not a differentiator)'. Do not invent a "
    "difference where the groups look alike; saying 'no reliable difference on "
    "X' is a valid and valuable answer."
)

_TITLE_SYS = (
    "You are a YouTube title strategist. " + _CONTRAST_RULE + "\n"
    "Distill a concise PLAYBOOK another creator can copy: the recurring formulas, "
    "power words, emotional triggers, number/bracket usage and ideal length that "
    "are present in WINNER titles and ABSENT (or much rarer) in CONTROL titles. "
    "End with 3 fill-in-the-blank title templates. Be specific and terse "
    "(<=200 words). Output plain text, no preamble."
)

_DIGEST_SYS = (
    "You are a YouTube retention analyst. You will receive the transcript of ONE "
    "video (possibly in sequential parts). Produce a compact, factual DIGEST — no "
    "praise, no advice:\n"
    "1. HOOK (first ~30s): what type (stat/question/pain/promise/story/cold-open) "
    "and what it promises.\n"
    "2. BEATS: the ordered segments with roughly where each starts (early/mid/late).\n"
    "3. OPEN LOOPS & RE-HOOKS: where a question is planted and where it is paid off.\n"
    "4. PACING: sentence rhythm, how often a new concrete idea/number lands.\n"
    "5. CTA: what is asked, and where.\n"
    "6. CLOSE: how it ends.\n"
    "<=160 words, plain text, no preamble."
)

_SCRIPT_SYS = (
    "You are a YouTube retention strategist. " + _CONTRAST_RULE + "\n"
    "You receive DIGESTS of full videos, each labelled WINNER (pair N) or "
    "CONTROL (pair N) — the same N means the same channel and the same matched "
    "pair, so contrast within a pair before generalising. A digest labelled "
    "WINNER (uncontrolled) has no counterpart: use it for hypotheses only. "
    "Reverse-engineer a SCRIPT PLAYBOOK covering: 1. HOOK formula, 2. STRUCTURE "
    "(beats and where open loops are planted/paid), 3. PACING, 4. RETENTION "
    "TACTICS, 5. TONE & LANGUAGE. For each, state the winner behaviour and the "
    "control behaviour it differs from. End with a copyable 5-beat outline "
    "template. Specific and terse (<=240 words). Plain text, no preamble."
)

_THUMB_SYS = (
    "You are a senior YouTube thumbnail art director reverse-engineering a CTR "
    "playbook. " + _CONTRAST_RULE + "\n"
    "The images are given in order and labelled for you in the final message. "
    "Compare across 5 layers: 1. FOCAL POINT, 2. LAYOUT & COMPOSITION (including "
    "keeping elements clear of the bottom-right timestamp), 3. COLOR & CONTRAST "
    "(does it pop in dark mode?), 4. CTR PSYCHOLOGY (which emotion, and how it "
    "pairs with the title to open a curiosity loop), 5. TYPOGRAPHY (word count, "
    "font class, outline, mobile legibility). End with 3 fill-in-the-blank "
    "thumbnail RECIPES that reproduce the WINNER side of each difference. "
    "Specific and terse (<=240 words). Plain text, no preamble."
)


# ── Cohort assembly ──────────────────────────────────────────────────────────

async def _fetch_competitor_videos(
    channel, api_key: str, per_channel: int = VIDEOS_PER_CHANNEL
) -> dict[str, list[dict]]:
    """Fetch recent videos for each competitor channel, KEPT GROUPED BY CHANNEL.

    The grouping is the point: a channel median cannot be computed once the
    videos have been poured into one flat list."""
    # Both the lazy imports (~540ms cold, mostly yt-dlp/httpx trees) and the
    # AsyncClient construction (~40ms every time, parsing a 240KB CA bundle) are
    # synchronous work that was running on the event loop.
    def _build_client():
        import httpx

        from omnicast.discovery.youtube_scanner import YouTubeScanner as _Scanner

        return httpx.AsyncClient(timeout=30), _Scanner

    http, _scanner_cls = await asyncio.to_thread(_build_client)
    # Resolved through the module so tests that patch
    # omnicast.discovery.youtube_scanner.YouTubeScanner still take effect.
    from omnicast.discovery import youtube_scanner as _ys

    scanner_cls = getattr(_ys, "YouTubeScanner", _scanner_cls)
    try:
        scanner = scanner_cls(config=channel, api_key=api_key, http_client=http)
        ids = list(getattr(channel, "competitor_channel_ids", []) or [])
        for handle in getattr(channel, "competitor_handles", []) or []:
            try:
                ids.append(await scanner._resolve_handle(handle))
            except Exception as exc:
                logger.warning("handle resolve failed", handle=handle, error=str(exc))

        by_channel: dict[str, list[dict]] = {}
        for cid in ids:
            try:
                pl = await scanner._get_channel_uploads_playlist_id(cid)
                vid_ids = await scanner._get_recent_video_ids(pl, max_results=per_channel)
                videos = await scanner._get_video_stats(vid_ids)
                if videos:
                    by_channel[cid] = videos
            except Exception as exc:
                logger.warning("competitor scan failed", channel=cid, error=str(exc))
        return by_channel
    finally:
        await http.aclose()


async def build_competitor_cohort(
    channel, api_key: str, *, max_winners: int = 12,
    per_channel: int = VIDEOS_PER_CHANNEL, video_filter=None
) -> tuple[Cohort, dict[str, dict]]:
    """Winner + matched-control cohort for a channel's competitor set.

    Returns the cohort and a video_id → raw video dict lookup (thumbnails,
    duration, tags) for the stages that need more than the cohort row carries.

    `video_filter` narrows the corpus BEFORE selection — used to learn a
    pillar-specific playbook. It has to happen before, not after: a channel
    median computed over every video and then filtered would judge annuity
    videos against the channel's all-topic baseline, which is a different
    question from "what wins within this pillar"."""
    by_channel = await _fetch_competitor_videos(channel, api_key, per_channel=per_channel)
    if video_filter is not None:
        by_channel = {
            cid: [v for v in videos if video_filter(v)]
            for cid, videos in by_channel.items()
        }
        by_channel = {cid: videos for cid, videos in by_channel.items() if videos}
    cohort = select_cohort(by_channel, max_winners=max_winners)
    by_id = {v["video_id"]: v
             for videos in by_channel.values() for v in videos if v.get("video_id")}
    logger.info(
        "competitor cohort built",
        channels=len(by_channel),
        winners=len(cohort.winners),
        controls=len(cohort.controls),
        comparable=cohort.is_comparable,
    )
    return cohort, by_id


async def _all_competitor_videos(channel, api_key: str, top_n: int = 20) -> list[dict]:
    """Flat list of competitor videos, most-viewed first.

    NOT for learning — view-sorting is exactly the bias the cohort work removed.
    This exists for jobs that only need a pile of video IDs to mine (e.g. the
    BGM credit harvester reading video descriptions), where no causal claim is
    made about why those videos did well."""
    by_channel = await _fetch_competitor_videos(channel, api_key)
    videos = [v for group in by_channel.values() for v in group]
    videos.sort(key=lambda v: v.get("views", 0), reverse=True)
    return videos[:top_n]


def _stamp(text: str, cohort: Cohort) -> str:
    """Mark a playbook with how much of it was actually controlled.

    Three states, because there are three: fully controlled (no stamp), some
    winners controlled (partial stamp naming the counts), none (uncontrolled)."""
    if not text:
        return text
    state = cohort.comparability
    if state == "full":
        return text
    if state == "partial":
        return _partial_stamp(cohort) + text
    return UNCONTROLLED_STAMP + text


def _labelled_titles(cohort: Cohort) -> str:
    """Contrast input that PRESERVES the pairing.

    The previous version emitted two flat lists. A model reading "here are 12
    winners, here is 1 control" cannot tell which control belongs to which
    winner, or that eleven winners have none — so it contrasts group means
    across channels, which is precisely the cross-channel comparison the cohort
    was built to avoid. Pairs are now explicit, and each carries its channel."""
    lines: list[str] = []
    pairs = cohort.matched_pairs
    if pairs:
        lines.append(
            "MATCHED PAIRS — each WINNER is followed by the CONTROL from the SAME "
            "channel it must be contrasted against. Compare WITHIN a pair first; "
            "only then look for a pattern that repeats across pairs."
        )
        for idx, (winner, controls) in enumerate(pairs, start=1):
            lines.append("")
            lines.append(f"PAIR {idx} (channel {winner.channel_id}):")
            lines.append(
                f"  WINNER  [{winner.outlier_ratio:.1f}x, "
                f"{winner.views_per_day:,.0f} views/day] {winner.title}"
            )
            for control in controls:
                flag = "" if control.format_matched else "  (TITLE FORMAT DIFFERS — "\
                    "a format difference in this pair may be an artefact of matching)"
                lines.append(
                    f"  CONTROL [{control.outlier_ratio:.1f}x, "
                    f"{control.views_per_day:,.0f} views/day] {control.title}{flag}"
                )
    unmatched = cohort.unmatched_winners
    if unmatched:
        lines.append("")
        lines.append(
            "UNCONTROLLED WINNERS — no ordinary sibling video could be matched to "
            "these. They may inform a hypothesis; they may NOT be used as "
            "evidence that a trait separates winners from ordinary videos:"
        )
        for winner in unmatched:
            lines.append(
                f"- [{winner.outlier_ratio:.1f}x, {winner.views_per_day:,.0f} "
                f"views/day, channel {winner.channel_id}] {winner.title}"
            )
    if not pairs:
        lines.append("")
        lines.append(
            "CONTROLS: none could be matched to any winner — say so rather than "
            "guessing."
        )
    return "\n".join(lines)


# ── Title playbook ───────────────────────────────────────────────────────────

async def _learn_titles(llm, cohort: Cohort) -> str:
    if not cohort.winners:
        return ""
    try:
        resp = await llm.complete(
            system=_TITLE_SYS,
            messages=[{"role": "user", "content": _labelled_titles(cohort)}],
            max_tokens=650,
            temperature=0.4,
        )
        return _stamp((resp.content or "").strip(), cohort)
    except Exception as exc:
        logger.warning("title playbook failed", error=str(exc))
        return ""


# ── Thumbnail playbook ───────────────────────────────────────────────────────

def _fetch_thumbs(thumb_urls: list[str], limit: int = 8,
                  deadline: float | None = None) -> list[bytes]:
    """Download thumbnails under a WALL-CLOCK budget and a size cap.

    Two separate bugs lived here. `timeout=` on urlopen bounds each socket
    operation, not the transfer: a peer dribbling one byte every two seconds
    holds the connection open indefinitely without ever tripping it. And a
    deadline checked only at the top of the loop does not bound the request it
    is already inside — measured 80s spent against a 45s "budget". So the read
    is chunked and the clock is checked BETWEEN chunks.

    `deadline` is passed in so the two calls (winners, then controls) share one
    budget instead of getting 45 seconds each."""
    import urllib.request

    out: list[bytes] = []
    if deadline is None:
        deadline = time.monotonic() + THUMB_TOTAL_DEADLINE_SECONDS
    for u in [x for x in thumb_urls if x][:limit]:
        if time.monotonic() >= deadline:
            logger.warning("thumbnail budget exhausted", fetched=len(out),
                           requested=min(len(thumb_urls), limit))
            break
        try:
            req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=THUMB_SOCKET_TIMEOUT) as r:
                buffer = bytearray()
                while len(buffer) <= THUMB_MAX_BYTES:
                    if time.monotonic() >= deadline:
                        buffer = bytearray()   # abandon the partial download
                        break
                    chunk = r.read(64 * 1024)
                    if not chunk:
                        break
                    buffer.extend(chunk)
            if not buffer:
                continue
            if len(buffer) > THUMB_MAX_BYTES:
                logger.warning("thumbnail too large, skipped", url=u[:120])
                continue
            out.append(bytes(buffer))
        except Exception:
            continue
    return out


def _thumb_urls(cohort: Cohort, by_id: dict[str, dict], per_group: int = 5
                ) -> tuple[list[str], list[str]]:
    """Thumbnail URLs for the vision contrast, ALIGNED BY PAIR.

    Winner i and control i are the same pair, from the same channel. The old
    version took the first 5 winners and the first 5 controls independently, so
    the lists could describe different channels entirely — and the vision model
    was told only "the first N are winners", which invited it to compare group
    aesthetics across channels rather than within a pair.

    A pair is included only when BOTH thumbnails resolve; a half pair would put
    the lists back out of step. If no complete pair survives, winners are
    returned alone and the caller states that nothing was verified."""
    def url(row) -> str:
        return (by_id.get(row.video_id) or {}).get("thumbnail_url", "")

    winners: list[str] = []
    controls: list[str] = []
    for winner, matched in cohort.matched_pairs:
        if len(winners) >= per_group:
            break
        winner_url = url(winner)
        control_url = next((u for u in (url(c) for c in matched) if u), "")
        if winner_url and control_url:
            winners.append(winner_url)
            controls.append(control_url)

    if not winners:
        for row in cohort.winners[:per_group]:
            found = url(row)
            if found:
                winners.append(found)
    return winners, controls


async def _learn_thumbnails_async(cohort: Cohort, by_id: dict[str, dict], **kwargs) -> str:
    """Off-loop wrapper around `_learn_thumbnails`.

    That function downloads up to 10 thumbnails over urllib at a 15s timeout
    each and then calls the Gemini/Anthropic SDKs synchronously — worst case a
    couple of minutes with the event loop held. It was being awaited-adjacent
    (called directly) from inside an async handler."""
    return await _in_research_pool(_learn_thumbnails, cohort, by_id, **kwargs)


def _learn_thumbnails(cohort: Cohort, by_id: dict[str, dict], google_key: str = "",
                      claude_key: str = "", claude_model: str = "claude-sonnet-5") -> str:
    """Vision contrast of winner vs control thumbnails → CTR design playbook.
    Prefers Gemini 2.5-flash (cheap), falls back to Claude vision. '' if no key/images.

    BLOCKING (network + sync SDK) — coroutines must use
    `_learn_thumbnails_async`."""
    if not (claude_key or google_key):
        return ""
    winner_urls, control_urls = _thumb_urls(cohort, by_id)
    # ONE budget for the whole stage, not one per group.
    deadline = time.monotonic() + THUMB_TOTAL_DEADLINE_SECONDS
    winner_imgs = _fetch_thumbs(winner_urls, deadline=deadline)
    control_imgs = _fetch_thumbs(control_urls, deadline=deadline)
    if not winner_imgs:
        return ""

    # A pair is only usable if BOTH its images downloaded; `_fetch_thumbs` can
    # drop one side (timeout, oversize), which would silently shift the mapping.
    pairs = min(len(winner_imgs), len(control_imgs))
    if control_imgs and pairs:
        winner_imgs, control_imgs = winner_imgs[:pairs], control_imgs[:pairs]
    else:
        control_imgs = []

    imgs = winner_imgs + control_imgs
    if control_imgs:
        legend = (
            f"There are {pairs} MATCHED PAIRS. Images 1-{pairs} are WINNER "
            f"thumbnails; images {pairs + 1}-{2 * pairs} are their CONTROLS, in "
            f"the SAME order — image {pairs + 1} is the control for image 1, and "
            "so on. Each pair is from one channel. Compare WITHIN each pair "
            "first, then report only what repeats across pairs."
        )
    else:
        legend = (
            f"All {len(winner_imgs)} image(s) are WINNER thumbnails. No controls "
            "were available, so state plainly that differences from ordinary "
            "videos could not be verified, then describe what the winners share."
        )

    # 1) Gemini 2.5-flash (cheap, default).
    if google_key:
        try:
            from google import genai
            from google.genai import types

            parts = [types.Part.from_bytes(data=b, mime_type="image/jpeg") for b in imgs]
            client = genai.Client(
                api_key=google_key,
                http_options=types.HttpOptions(timeout=VISION_TIMEOUT_SECONDS * 1000),
            )
            resp = client.models.generate_content(
                model="gemini-2.5-flash", contents=[*parts, _THUMB_SYS, legend])
            txt = (resp.candidates[0].content.parts[0].text or "").strip()
            if txt:
                logger.info("thumbnail playbook via Gemini",
                            winners=len(winner_imgs), controls=len(control_imgs))
                return _stamp(txt, cohort)
        except Exception as exc:
            logger.warning("gemini thumbnail analysis failed", error=str(exc))

    # 2) Claude vision fallback (when no Google key).
    if claude_key:
        try:
            import base64

            import anthropic

            blocks = [{"type": "image", "source": {
                "type": "base64", "media_type": "image/jpeg",
                "data": base64.b64encode(b).decode()}} for b in imgs]
            blocks.append({"type": "text", "text": legend})
            client = anthropic.Anthropic(api_key=claude_key,
                                         timeout=VISION_TIMEOUT_SECONDS)
            msg = client.messages.create(
                model=claude_model, max_tokens=900, system=_THUMB_SYS,
                messages=[{"role": "user", "content": blocks}])
            txt = "".join(b.text for b in msg.content
                          if getattr(b, "type", "") == "text").strip()
            if txt:
                logger.info("thumbnail playbook via Claude",
                            winners=len(winner_imgs), controls=len(control_imgs))
                return _stamp(txt, cohort)
        except Exception as exc:
            logger.warning("claude thumbnail analysis failed", error=str(exc))
    return ""


# ── Script playbook ──────────────────────────────────────────────────────────

def _fetch_transcript(video_id: str, duration_minutes: float = 0.0) -> Transcript:
    """Full transcript for one competitor video (captions, else ASR).

    BLOCKING: HTTP for captions, and on the ASR path a yt-dlp download plus
    minutes of CPU-bound Whisper. Never call this directly from a coroutine —
    use `_fetch_transcript_async`. Kept as a thin seam so tests can substitute
    a fixed transcript."""
    return fetch_transcript(video_id, duration_minutes=duration_minutes)


async def _fetch_transcript_async(video_id: str, duration_minutes: float = 0.0) -> Transcript:
    """Off-loop wrapper around `_fetch_transcript`.

    `learn_for_channel` is awaited from inside the FastAPI app. A single
    caption-less 40-minute video on the ASR path would otherwise freeze every
    other request on that worker for the duration of the transcription.
    Resolved through the module global so tests can still patch
    `_fetch_transcript`."""
    return await _in_research_pool(_fetch_transcript, video_id, duration_minutes)


async def _digest_video(llm, label: str, title: str, transcript: Transcript) -> str:
    """Compress ONE full transcript into a structural digest.

    Map step of a map-reduce: the whole video reaches the model in sequential
    chunks, and only the digest — not the raw 20k characters — is carried into
    the cross-video synthesis. This is what replaced `transcript[:3500]`."""
    chunks = transcript.chunks(max_chars=TRANSCRIPT_CHUNK_CHARS)
    if not chunks:
        return ""
    dropped = 0
    if len(chunks) > MAX_CHUNKS_PER_VIDEO:
        dropped = len(chunks) - MAX_CHUNKS_PER_VIDEO
        chunks = chunks[:MAX_CHUNKS_PER_VIDEO]
    body = "\n\n".join(
        f"--- part {i + 1} of {len(chunks)} ---\n{c}" for i, c in enumerate(chunks)
    )
    user = f"Video: {title or '(untitled)'}\nSource: {transcript.describe()}\n\n{body}"
    if dropped:
        user += (
            f"\n\n[NOTE: {dropped} later part(s) of this transcript were not "
            "included — say nothing about how the video ends.]"
        )
    try:
        resp = await llm.complete(
            system=_DIGEST_SYS,
            messages=[{"role": "user", "content": user}],
            max_tokens=400,
            temperature=0.3,
        )
        digest = (resp.content or "").strip()
    except Exception as exc:
        logger.warning("transcript digest failed", video_id=transcript.video_id, error=str(exc))
        return ""
    if not digest:
        return ""
    return f"### {label}: {title or '(untitled)'}\n{digest}"


async def _learn_scripts(llm, cohort: Cohort, by_id: dict[str, dict],
                         top_n: int = SCRIPT_SAMPLE_WINNERS,
                         collect: list[dict] | None = None) -> tuple[str, list[str]]:
    """Distill a script playbook by contrasting winner and control structure.

    Returns (playbook, notes) — notes record every video that dropped out of the
    sample and why, so a thin sample is never mistaken for a strong signal.

    `collect`, when given, receives one row per WINNER whose transcript was
    usable: {video_id, title, duration_minutes, transcript}. Passing a list
    rather than changing the return arity keeps every existing caller working,
    and it means the production blueprint is measured from transcripts this
    function already paid for instead of fetching them a second time."""
    notes: list[str] = []
    if not cohort.winners:
        return "", notes

    # Spend the transcript budget on winners that can actually be contrasted.
    # Taking `winners[:top_n]` off the top meant a run could burn all N slots on
    # winners with no control and then report a "contrast" with nothing to
    # contrast against.
    ordered = cohort.matched_winners + cohort.unmatched_winners
    winners = ordered[:top_n]
    dropped_uncontrolled = len(cohort.unmatched_winners) - sum(
        1 for w in winners if not cohort.controls_for(w.video_id))
    if dropped_uncontrolled > 0:
        notes.append(
            f"{dropped_uncontrolled} uncontrolled winner(s) left out of the "
            "script sample — matched pairs were preferred")

    pair_no = {w.video_id: i for i, w in enumerate(winners, start=1)}
    labelled: list[tuple[object, str]] = []
    for winner in winners:
        tag = f"pair {pair_no[winner.video_id]}"
        matched = cohort.controls_for(winner.video_id)
        labelled.append((winner, f"WINNER ({tag})" if matched else "WINNER (uncontrolled)"))
        labelled.extend((c, f"CONTROL ({tag})") for c in matched)

    digests: list[str] = []
    for row, label in labelled:
        duration = float((by_id.get(row.video_id) or {}).get("duration_minutes", 0) or 0)
        try:
            transcript = await _fetch_transcript_async(
                row.video_id, duration_minutes=duration)
        except ResearchPoolBusy as exc:
            notes.append(f"{label} {row.video_id}: skipped — {exc}")
            continue
        if not transcript.ok:
            notes.append(f"{label} {row.video_id}: no transcript ({transcript.note})")
            continue
        if collect is not None and label.startswith("WINNER"):
            # P0.1 group 4: video_intel had no production caller, and the reason
            # was structural — the only place in the system that holds real
            # competitor transcripts is right here, and it threw them away after
            # summarising them. Blueprints are measured from WINNERS only: the
            # question a blueprint answers is "how is a video that wins made",
            # and averaging the controls back in dilutes exactly that.
            collect.append({
                "video_id": row.video_id,
                "title": row.title,
                "duration_minutes": duration or row.duration_minutes,
                "transcript": transcript,
            })
        digest = await _digest_video(llm, label, row.title, transcript)
        if digest:
            digests.append(digest)
        else:
            notes.append(f"{label} {row.video_id}: digest failed")

    if not any(d.startswith("### WINNER") for d in digests):
        notes.append("script playbook skipped: no winner transcript was usable")
        return "", notes

    control_digests = sum(1 for d in digests if d.startswith("### CONTROL"))
    if not control_digests:
        notes.append("script playbook is winner-only: no control transcript was usable")

    user = "Video digests:\n\n" + "\n\n".join(digests)
    try:
        resp = await llm.complete(
            system=_SCRIPT_SYS,
            messages=[{"role": "user", "content": user}],
            max_tokens=800,
            temperature=0.4,
        )
        playbook = (resp.content or "").strip()
    except Exception as exc:
        logger.warning("script playbook failed", error=str(exc))
        return "", notes

    if playbook and not control_digests:
        playbook = UNCONTROLLED_STAMP + playbook
    return _stamp(playbook, cohort), notes


# ── Production blueprint (P0.1 group 4) ──────────────────────────────────────

async def _measure_production(niche_key: str, measured: list[dict]
                              ) -> tuple[dict | None, list[str]]:
    """Turn the winner transcripts this run already fetched into a blueprint.

    THIS IS THE DECISION THE HANDOFF ASKED FOR. `analytics.video_intel` had no
    production caller: it was measured, tested, and never run. The choice was to
    wire one vertical slice or to mark the module dead. It is wired here, on the
    only path in the system that holds real competitor transcripts.

    What this slice can and cannot see, stated once so nobody has to infer it:

      * CAN measure — hook type and its evidence, beat structure from real cue
        timings, words per minute, runtime.
      * CAN measure, WHEN `OMNICAST_COMPETITOR_FORENSICS=1` — shot rhythm,
        motion mix, colour mood and transition grammar, by pulling a low-res
        copy of the top winners and measuring the frames (see
        `analytics.av_fetch`). The copy is deleted as soon as it is measured.
      * CANNOT measure, ever, from here — art style, b-roll ratio and
        text-overlay frequency. Those need a vision model, and
        `build_blueprint` keeps them in `assumed_fields`.
      * With the flag off (the default) nothing visual is fetched and the
        blueprint reports the visual fields as unmeasured, exactly as before.
        Pretending otherwise is precisely the failure this module was rewritten
        to stop.
    """
    notes: list[str] = []
    if not measured:
        return None, ["production blueprint skipped: no winner transcript was usable"]

    from omnicast.analytics.video_intel import VideoIntelligenceAnalyzer

    from omnicast.analytics import av_fetch

    analyzer = VideoIntelligenceAnalyzer()
    forensics_on = av_fetch.forensics_enabled()
    if not forensics_on:
        notes.append(
            "competitor audiovisual forensics is OFF — set "
            f"{av_fetch.ENV_FLAG}=1 to measure shot rhythm, motion and colour "
            "from the winners' frames; until then every visual field is "
            "unmeasured")
    analyses: list[dict] = []
    for row in measured:
        transcript = row["transcript"]
        duration_minutes = float(row.get("duration_minutes") or 0.0)
        try:
            structure = await analyzer.analyze_structure(
                transcript, duration_seconds=duration_minutes * 60.0)
            hook = await analyzer.analyze_hook(transcript)
            audio = await analyzer.analyze_audio_pattern(
                {}, transcript=transcript, duration_seconds=duration_minutes * 60.0)
        except Exception as exc:
            notes.append(f"blueprint: {row['video_id']} analysis failed ({exc})")
            continue
        analysis = {
            "video_id": row["video_id"],
            "title": row.get("title", ""),
            "duration_minutes": duration_minutes,
            "structure": structure,
            "hook": hook,
            "audio": audio,
        }
        # A visual block ONLY when frames were actually measured. Omitting it
        # says "not attempted", which is the truth when the flag is off; an
        # empty dict would be counted as an unmeasured block and quietly drag
        # confidence down for a measurement nobody asked for.
        if forensics_on:
            try:
                grammar = await asyncio.to_thread(
                    av_fetch.measure_competitor_video,
                    row["video_id"], transcript=transcript,
                    duration_minutes=duration_minutes)
            except Exception as exc:
                grammar = None
                notes.append(f"forensics {row['video_id']}: failed ({exc})")
            if grammar:
                analysis["visual"] = _forensics_visual_block(grammar)
            else:
                notes.append(
                    f"forensics {row['video_id']}: no frames measured "
                    "(download unavailable, too long, or ffmpeg missing)")
        analyses.append(analysis)

    if not analyses:
        return None, notes or ["production blueprint skipped: no analysis succeeded"]

    blueprint = await analyzer.build_blueprint(niche_key, analyses)
    notes.extend(blueprint.notes)
    payload = blueprint.model_dump(mode="json")
    return payload, notes


def _forensics_visual_block(grammar: dict) -> dict:
    """Turn an `av_forensics` report into the `visual` block build_blueprint reads.

    Same shape as `VideoIntelligenceAnalyzer.analyze_forensics` produces for our
    own renders, so a competitor blueprint and our own are directly comparable —
    which is the whole point of measuring theirs."""
    return {
        "measured": grammar.get("field_status", {}).get("shots") == "measured",
        "source": "av_forensics",
        "art_direction": "unknown",
        "b_roll_ratio": 0.0,
        "text_overlay_freq": 0.0,
        "color_mood": grammar.get("colour_mood", "unknown"),
        "scene_count": grammar.get("shot_count"),
        "median_shot_seconds": grammar.get("median_shot_seconds"),
        "cuts_per_minute": grammar.get("cuts_per_minute"),
        "motion_mix": grammar.get("motion_mix"),
        "transition_mix": grammar.get("transition_mix"),
        "text_overlay_proxy": grammar.get("text_overlay_proxy"),
        "silence_ratio": grammar.get("silence_ratio"),
        "forensics": grammar,
        "notes": list(grammar.get("notes") or []),
    }


# ── Audience, schedule and pillars (brief §4.2, §4.4, §4.6) ──────────────────

# Comments are fetched for the top winners only. Every fetch is a quota call and
# a network round trip, and the marginal value of the twelfth video's comment
# section is close to zero.
COMMENT_SAMPLE_WINNERS = 4
COMMENTS_PER_VIDEO = 100


async def _learn_audience(channel, cohort: Cohort):
    """Read what viewers actually said under the winning videos.

    `fetch_comments` was made real in P0 and then read by nobody: the scanner
    still used only the COUNT. This is the reader."""
    from omnicast.analytics.comment_intel import analyse_comments

    notes: list[str] = []
    try:
        from omnicast.platforms.youtube import YouTubeAdapter
    except Exception as exc:
        return None, [f"audience signals skipped: adapter unavailable ({exc})"]

    try:
        adapter = YouTubeAdapter(channel)
    except Exception as exc:
        return None, [f"audience signals skipped: adapter init failed ({exc})"]

    collected: list[dict] = []
    statuses: list[str] = []
    for winner in cohort.winners[:COMMENT_SAMPLE_WINNERS]:
        try:
            fetched = await adapter.fetch_comments(
                winner.video_id, max_comments=COMMENTS_PER_VIDEO)
        except Exception as exc:
            notes.append(f"comments {winner.video_id}: fetch failed ({exc})")
            continue
        status = getattr(fetched, "status", "ok")
        statuses.append(status)
        if status != "ok":
            notes.append(f"comments {winner.video_id}: {status}")
            continue
        collected.extend(fetched)

    if not collected:
        # Distinguish "every fetch failed" from "the videos genuinely had no
        # comments" — they call for completely different follow-up.
        reason = statuses[0] if len(set(statuses)) == 1 and statuses else "no comments"
        notes.append(f"audience signals: nothing to analyse ({reason})")
        return None, notes

    intel = analyse_comments(collected)
    intel.sample["videos_sampled"] = min(len(cohort.winners), COMMENT_SAMPLE_WINNERS)
    notes.extend(intel.notes)
    return intel, notes


def _pillar_classifier(channel):
    """(callable, summary_holder) or (None, None) when no pillars are declared."""
    from omnicast.analytics.pillars import classify_pillar, load_pillars

    pillars = load_pillars(getattr(channel, "content_pillars", None))
    if not pillars:
        return None, None

    summary = {"total": 0, "classified": 0, "by_pillar": {}}

    def classify(video: dict) -> str:
        match = classify_pillar(video.get("title", ""),
                                video.get("description", ""), pillars)
        summary["total"] += 1
        if match.is_classified:
            summary["classified"] += 1
        summary["by_pillar"][match.pillar_id] = \
            summary["by_pillar"].get(match.pillar_id, 0) + 1
        return match.pillar_id

    return classify, summary


# ── Orchestration ────────────────────────────────────────────────────────────

ARTIFACT_FIELDS = ("title_playbook", "thumbnail_playbook", "script_playbook")

# Artifacts that live inside `cohort_meta` rather than in their own column.
# They go through the SAME merge rule as the text playbooks — artifact and
# provenance move together — so a blueprint carried forward from an earlier run
# keeps that run's id and comparability instead of borrowing this run's.
META_ARTIFACT_FIELDS = ("production_blueprint", "schedule", "audience_signals",
                        "dossier")


def _merge_run(previous, produced: dict[str, str], run_provenance: dict,
               meta_produced: dict | None = None
               ) -> tuple[dict[str, str], dict]:
    """Combine this run's artifacts with whatever must be carried forward.

    The rule: an artifact and its provenance move TOGETHER. A run that failed to
    produce a script playbook may keep the previous one — but it keeps the
    previous one's run id, timestamp and comparability too, so the gate judges
    the text that actually exists rather than the cohort that happens to be
    newest. The old SQL kept the artifact and replaced the metadata, which is
    how a playbook learned with no control group could later read as verified.
    """
    previous_meta: dict = {}
    if previous is not None:
        try:
            previous_meta = json.loads(getattr(previous, "cohort_meta", "") or "{}")
            if not isinstance(previous_meta, dict):
                previous_meta = {}
        except Exception:
            previous_meta = {}
    previous_artifacts = previous_meta.get("artifacts") or {}

    final: dict[str, str] = {}
    artifacts: dict[str, dict] = {}
    carried: list[str] = []

    for field_name in ARTIFACT_FIELDS:
        fresh = (produced.get(field_name) or "").strip()
        if fresh:
            final[field_name] = fresh
            artifacts[field_name] = dict(run_provenance)
            continue
        inherited = (getattr(previous, field_name, "") or "").strip() if previous else ""
        if inherited:
            final[field_name] = inherited
            # No per-artifact record on the older row (pre-migration): fall back
            # to that row's run-level provenance, never to this run's.
            inherited_meta = dict(previous_artifacts.get(field_name) or {}) or {
                k: v for k, v in previous_meta.items()
                if k in {"research_run_id", "generated_at", "is_comparable",
                         "winner_count", "control_count"}
            }
            if not inherited_meta:
                # Nothing known about where this text came from. Say exactly
                # that. An empty dict would let the gate fall through to the
                # row's metadata — i.e. to THIS run's credentials — which is the
                # laundering this whole function exists to stop.
                inherited_meta = {"research_run_id": "", "generated_at": "",
                                  "is_comparable": None, "provenance": "unknown"}
            artifacts[field_name] = inherited_meta
            carried.append(field_name)
        else:
            final[field_name] = ""

    # Artifacts stored inside cohort_meta (currently just the production
    # blueprint). Same rule, same failure mode if it were skipped: a run that
    # measured nothing would otherwise republish the previous blueprint under
    # this run's credentials.
    meta_final: dict = {}
    for field_name in META_ARTIFACT_FIELDS:
        fresh_value = (meta_produced or {}).get(field_name)
        if fresh_value:
            meta_final[field_name] = fresh_value
            artifacts[field_name] = dict(run_provenance)
            continue
        inherited_value = previous_meta.get(field_name)
        if inherited_value:
            meta_final[field_name] = inherited_value
            inherited_meta = dict(previous_artifacts.get(field_name) or {}) or {
                "research_run_id": "", "generated_at": "",
                "is_comparable": None, "provenance": "unknown"}
            artifacts[field_name] = inherited_meta
            carried.append(field_name)

    merged = {"artifacts": artifacts, "carried_forward": carried}
    merged.update(meta_final)
    return final, merged


async def learn_for_channel(channel, niche_key: str = "", *,
                            pillar_id: str = "") -> dict | None:
    """Distill + persist competitor intelligence for this channel's SCOPE.

    Returns a summary dict, or None if nothing learnable.

    `niche_key` is now optional and, when omitted, is derived from the channel
    via `analytics.intel_scope` — channel/audience/format/market/pillar rather
    than the bare niche. Callers that still pass `channel.niche.value` keep
    working and keep writing the old broad key; the writer's fallback chain
    reads both. Passing nothing is the correct call for new code.

    `pillar_id` learns a playbook for ONE declared content pillar: the
    competitor corpus is filtered to that pillar before the cohort is built, and
    the row is written under the pillar-scoped key. Without it the run writes at
    the channel-wide level (pillar `*`), which is a real and useful scope — a
    channel with no pillars declared has nothing finer to say — but it is NOT
    the same row, and a writer whose brief carries a pillar will prefer the
    pillar row and fall back to this one.
    """
    from omnicast.capabilities.llm_factory import create_llm
    from omnicast.config.settings import get_settings
    from omnicast.vault import db as vault_db
    from omnicast.vault.models import CompetitorIntel

    from omnicast.analytics.intel_scope import scope_key as _scope_key

    niche_key = niche_key or _scope_key(channel, pillar_id=pillar_id)

    s = get_settings()
    api_key = s.youtube_api_key
    if not api_key:
        return None

    # A separate classifier instance for filtering: `_pillar_classifier` tallies
    # every call, and sharing one between the corpus filter and the schedule
    # summary would count each video twice.
    filter_of, _discarded_summary = _pillar_classifier(channel)
    video_filter = None
    if pillar_id:
        if filter_of is None:
            logger.warning("pillar requested but none are declared on the channel",
                           channel=getattr(channel, "channel_id", ""), pillar=pillar_id)
            return None

        def video_filter(video: dict) -> bool:  # noqa: F811 — narrow, local
            return filter_of(video) == pillar_id

    cohort, by_id = await build_competitor_cohort(
        channel, api_key, video_filter=video_filter)
    if not cohort.winners:
        logger.info("no competitor winners cleared the outlier threshold",
                    niche=niche_key, pillar=pillar_id, notes=cohort.notes[:5])
        return None

    titles = [w.title for w in cohort.winners if w.title]

    # One research run = one id. Everything this run produces is stamped with it,
    # so a downstream reader can always answer "which cohort produced this text".
    run_id = uuid.uuid4().hex[:12]
    generated_at = datetime.now(timezone.utc).isoformat()

    # create_llm is synchronous and heavier than it looks: it opens several
    # sqlite connections (capability registry, key pool, budget guard) and can
    # shell out to nvidia-smi while probing local candidates. Measured ~190ms of
    # event-loop stall cold, on a coroutine served by the API worker.
    llm = await asyncio.to_thread(
        create_llm, default_provider="deepseek", model=s.deepseek_flash_model)
    title_pb = await _learn_titles(llm, cohort)
    try:
        thumb_pb = await _learn_thumbnails_async(
            cohort, by_id, google_key=s.google_api_key, claude_key=s.claude_api_key,
            claude_model=s.claude_model)
    except ResearchPoolBusy as exc:
        logger.warning("thumbnail playbook skipped", reason=str(exc))
        thumb_pb = ""
    measured_winners: list[dict] = []
    script_pb, script_notes = await _learn_scripts(
        llm, cohort, by_id, collect=measured_winners)
    blueprint, blueprint_notes = await _measure_production(niche_key, measured_winners)
    script_notes.extend(blueprint_notes)

    # §4.6 — the scanner has carried `published_at` all along and nothing ever
    # looked at it; the scheduler picked slots from a hard-coded table instead.
    from omnicast.analytics.schedule import analyse_schedule

    pillar_of, pillar_summary = _pillar_classifier(channel)
    schedule_profile = analyse_schedule(list(by_id.values()), pillar_of=pillar_of)
    schedule_notes = list(schedule_profile.notes)

    # §4.4 — read the comments that P0 made fetchable.
    audience, audience_notes = await _learn_audience(channel, cohort)

    # §4.5 — one artifact, every field labelled measured/inferred/assumed/missing.
    from omnicast.analytics.dossier import build_dossier
    from omnicast.analytics.intel_scope import dimensions_for

    dossier = build_dossier(
        scope={"key": niche_key, "pillar_id": pillar_id or "",
               **dimensions_for(channel, pillar_id=pillar_id)},
        cohort=cohort,
        playbooks={"title_playbook": title_pb, "thumbnail_playbook": thumb_pb,
                   "script_playbook": script_pb},
        blueprint=blueprint,
        schedule=schedule_profile,
        comments=audience,
        pillar_summary=pillar_summary,
        generated_at=generated_at,
    ).as_dict()

    schedule_payload = schedule_profile.as_dict() if schedule_profile.videos_analysed else None
    audience_payload = audience.as_dict() if audience is not None else None

    script_notes.extend(schedule_notes + audience_notes)
    if not title_pb and not thumb_pb and not script_pb and not blueprint:
        logger.warning("competitor intel run produced nothing", niche=niche_key,
                       research_run_id=run_id, notes=(cohort.notes + script_notes)[:5])
        return None

    run_provenance = {
        "research_run_id": run_id,
        "generated_at": generated_at,
        "is_comparable": cohort.is_comparable,
        # `is_comparable` is now the strict all-winners-matched answer, so a
        # partially controlled run reads as False there. The gate must still be
        # able to tell "1 of 12" from "0 of 12" without re-deriving it.
        "comparability": cohort.comparability,
        "control_coverage": round(cohort.control_coverage, 3),
        "matched_winner_count": len(cohort.matched_winners),
        "format_mismatched_pairs": cohort.format_mismatched_pairs,
        "winner_count": len(cohort.winners),
        "control_count": len(cohort.controls),
    }

    from pathlib import Path

    VAULT_DB = Path(__file__).resolve().parents[3] / "output" / "vault.db"

    captured: dict = {}

    def _persist() -> dict:
        """Read-merge-write in ONE exclusive transaction, off the event loop.

        The read and the write used to sit on separate connections, so two
        learners running for the same niche could interleave and the later one
        would drop the earlier one's carried-forward artifacts and provenance."""
        vault_db.init_db(VAULT_DB)

        def _build(previous):
            artifacts, merge_meta = _merge_run(
                previous,
                {"title_playbook": title_pb, "thumbnail_playbook": thumb_pb,
                 "script_playbook": script_pb},
                run_provenance,
                {"production_blueprint": blueprint,
                 "schedule": schedule_payload,
                 "audience_signals": audience_payload,
                 "dossier": dossier},
            )
            meta = {
                **run_provenance,
                "selection": cohort.as_packet()["selection"],
                "notes": cohort.notes + script_notes,
                **merge_meta,
            }
            captured.update(meta)
            return CompetitorIntel(
                niche=niche_key,
                title_playbook=artifacts["title_playbook"],
                thumbnail_playbook=artifacts["thumbnail_playbook"],
                script_playbook=artifacts["script_playbook"],
                sample_titles=titles[:15],
                sample_count=len(cohort.winners),
                cohort_meta=json.dumps(meta, ensure_ascii=False),
                updated_at=generated_at,
            )

        vault_db.replace_competitor_intel(niche_key, _build, VAULT_DB)
        return captured

    meta = await asyncio.to_thread(_persist)
    try:
        from omnicast.agents.writer import invalidate_competitor_intel_cache

        # The writer caches under the lowercased scope key.
        invalidate_competitor_intel_cache(str(niche_key).lower())
    except Exception as exc:  # never let cache housekeeping fail a run
        logger.warning("intel cache invalidation failed", error=str(exc))

    logger.info("competitor intel learned", niche=niche_key, research_run_id=run_id,
                winners=len(cohort.winners), controls=len(cohort.controls),
                comparable=cohort.is_comparable, has_title=bool(title_pb),
                has_thumb=bool(thumb_pb), has_script=bool(script_pb),
                carried_forward=meta.get("carried_forward", []))
    return {
        "niche": niche_key,
        "pillar_id": pillar_id or "",
        "research_run_id": run_id,
        "samples": len(cohort.winners),
        "winners": len(cohort.winners),
        "controls": len(cohort.controls),
        "is_comparable": cohort.is_comparable,
        "comparability": cohort.comparability,
        "control_coverage": round(cohort.control_coverage, 3),
        "title_playbook": bool(title_pb),
        "thumbnail_playbook": bool(thumb_pb),
        "script_playbook": bool(script_pb),
        "production_blueprint": bool(meta.get("production_blueprint")),
        "blueprint_confidence": (meta.get("production_blueprint") or {}).get("confidence"),
        "schedule": bool(meta.get("schedule")),
        "audience_signals": bool(meta.get("audience_signals")),
        "dossier_coverage": (meta.get("dossier") or {}).get("coverage"),
        "carried_forward": meta.get("carried_forward", []),
        "notes": meta["notes"][:10],
    }
