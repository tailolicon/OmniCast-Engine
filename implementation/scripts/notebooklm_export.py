"""Export NotebookLM research packets for the flagship competitor corpus.

PILOT SCOPE (GPT proposal 2026-07-26, steps 1-3, user-approved direction):
one enriched Markdown packet per cohort video (12 winners + 7 matched controls)
with performance metadata + winner/control labels + TIMESTAMPED transcript —
the four things a bare YouTube URL loses. Uploaded to a single pilot notebook
by multi-select file upload (no per-URL pasting).

Also emits the research protocol + the three tiered prompts (video card →
pair comparison → cohort synthesis) and a corpus manifest. Findings that come
back flow through the EXISTING intel gate (analytics.intel_gate) — a finding
without matched-control evidence is refused there, same as any playbook.

Usage:
    .venv/Scripts/python.exe scripts/notebooklm_export.py [--channel senior_wealth_us]

Output: output/research/<channel>/notebooklm/pilot/{sources/*.md, prompts/*.md,
        00_research_protocol.md, 00_manifest.csv, corpus_manifest.jsonl}
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_TAG_RE = re.compile(r"<[^>]+>")
_CUE_RE = re.compile(r"^(\d{2}):(\d{2}):(\d{2})\.\d{3} --> ")


def vtt_to_timestamped_text(vtt: str, block_seconds: int = 20) -> str:
    """Flatten rolling-caption VTT into deduplicated text with [mm:ss] markers
    roughly every `block_seconds` (fetch_transcripts.py drops timestamps —
    NotebookLM citations need them, so this parser keeps coarse ones)."""
    out: list[str] = []
    last_line = ""
    last_mark = -block_seconds
    cur_t = 0
    for raw in vtt.splitlines():
        line = raw.strip()
        m = _CUE_RE.match(line)
        if m:
            cur_t = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
            continue
        if (not line or line.startswith(("WEBVTT", "Kind:", "Language:", "NOTE"))
                or line.isdigit()):
            continue
        text = _TAG_RE.sub("", line).strip()
        if not text or text == last_line:
            continue
        if cur_t - last_mark >= block_seconds:
            out.append(f"\n[{cur_t // 60:02d}:{cur_t % 60:02d}]")
            last_mark = cur_t
        out.append(text)
        last_line = text
    return "\n".join(out).strip()


def fetch_vtt(video_id: str, tmp_dir: Path) -> str | None:
    import yt_dlp

    opts = {
        "skip_download": True, "writesubtitles": True, "writeautomaticsub": True,
        "subtitleslangs": ["en", "en-US", "en-orig"], "subtitlesformat": "vtt",
        "outtmpl": str(tmp_dir / "%(id)s.%(ext)s"), "quiet": True, "no_warnings": True,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([f"https://www.youtube.com/watch?v={video_id}"])
        files = sorted(tmp_dir.glob(f"{video_id}*.vtt"))
        return files[0].read_text(encoding="utf-8") if files else None
    except Exception as exc:  # noqa: BLE001
        print(f"  [warn] vtt fetch failed {video_id}: {str(exc)[:100]}")
        return None


def guess_pillar(title: str, pillars: list[dict]) -> str:
    low = title.lower()
    for p in pillars:
        if any(k.lower() in low for k in p.get("keywords", [])):
            return str(p.get("pillar_id", ""))
    return ""


def packet_md(video: dict, channel_cfg: dict, transcript: str,
              matched_control: str, transcript_method: str) -> str:
    role = video["role"]
    pillar = guess_pillar(video["title"], channel_cfg.get("content_pillars", []))
    return f"""# Video Research Packet — {'WINNER' if role == 'winner' else 'CONTROL'}

video_id: {video['video_id']}
channel: {video['channel_id']}
title: {video['title']}
url: https://www.youtube.com/watch?v={video['video_id']}

published_at: {video.get('published_at', '')}
duration_minutes: {video.get('duration_minutes', '')}
views: {video.get('views', '')}
views_per_day: {video.get('views_per_day', '')}
outlier_ratio_vs_own_channel_median: {video.get('outlier_ratio', '')}
engagement_rate: {video.get('engagement_rate', '')}

role: {role}
matched_control: {matched_control or 'NONE (winner-only evidence — weaker)'}
pillar: {pillar or 'unclassified'}
target_audience: US retirees 60-75
language: en-US
transcript_method: {transcript_method}

NOTE FOR ANALYSIS: outlier_ratio compares this video to ITS OWN channel's
median views/day — a winner won against its own channel's baseline, not
against bigger channels. Never attribute a winner trait to performance
without checking the matched control.

## Transcript (timestamped)

{transcript}
"""


PROTOCOL = """# Research Protocol — Senior Finance Competitor Pilot

SOURCES: {n_win} winner packets + {n_ctl} matched-control packets from
{n_ch} channels (scan {scan_date}). role/matched_control/outlier_ratio are in
each packet header. A winner = >=2x views/day vs its own channel's median,
settled >=7 days; its control = same channel, close in time and length.

RULES FOR EVERY ANSWER:
1. Use only the sources in this notebook. Cite video_id + [mm:ss] timestamps.
2. Winner-vs-control comparisons may ONLY pair a winner with the video named
   in its matched_control field. Winners with matched_control NONE give
   weaker, winner-only evidence — label it as such.
3. Never conclude a trait causes performance just because a winner has it —
   check whether the matched control has it too, and say so.
4. Findings are CORRELATIONAL. Offer at least one alternative explanation.
5. If sources cannot answer, reply INSUFFICIENT_EVIDENCE — do not guess.
6. Excerpts max 20 words. We extract MECHANISMS (structure, ordering,
   attribution style), never copyable sentences, metaphors or named stories.

WORKFLOW: run prompts in order — 1 source_audit, 2 video_card (per winner),
3 pair_comparison, 4 cohort_synthesis. Export answers back to the operator;
they pass through an automated evidence gate before any production use.
"""

PROMPT_SOURCE_AUDIT = """Prompt 1 — SOURCE AUDIT (run first, once)

For each source in this notebook, return one line:
video_id | role | matched_control | does the transcript text load correctly
(quote its first 8 words with timestamp)?
List any source whose transcript looks empty, truncated or mismatched with
its title. I need to verify indexing before trusting any analysis.
"""

PROMPT_VIDEO_CARD = """Prompt 2 — VIDEO CARD (run once per WINNER packet; replace VIDEO_ID)

Using only source VIDEO_ID, fill this schema. Describe, do not evaluate:

video_id:
audience_problem: (one sentence, the viewer pain this video answers)
opening:
  first_15s_function: (what the first 15 seconds do)
  promise: (what is promised, quote <=20 words + timestamp)
  stakes: (the consequence named, if any)
  curiosity_gap: (what is withheld)
structure:
  beat_count:
  beats: (ordered list, each with [mm:ss])
  open_loops: (tease -> where paid off, timestamps)
transitions: (how it moves between beats, 2 examples)
trust:
  authority_signals: (sources cited ALOUD, exact formula + timestamp)
  evidence_types: (report/law/example/story/number)
  disclaimers: (any, with timestamp)
retention:
  verbal_pattern_interrupts:
  delayed_payoffs:
cta:
  timing: [mm:ss]
  function: (subscribe/next-video/comment-question)
copy_risk:
  distinctive_phrases_not_to_copy: (3-5 signature phrasings unique to this host)
"""

PROMPT_PAIR_COMPARISON = """Prompt 3 — PAIR COMPARISON (run once, after video cards)

For every winner packet, compare it ONLY with the source named in its
matched_control field (skip winners whose matched_control is NONE, list them
at the end as unpaired).

Dimensions: 1 first 15 seconds; 2 clarity of promise; 3 stakes/consequences;
4 information reveal order; 5 open loops + delayed payoffs; 6 trust and
evidence (spoken attribution); 7 transitions; 8 CTA timing; 9 audience
specificity; 10 emotional frame (fear-warning vs empowerment-clarity).

For every meaningful difference return:
- winner video_id / control video_id
- observation
- evidence from BOTH sources (<=20-word excerpts + timestamps)
- alternative explanation
- confidence: low / medium / high
Do not assume a trait caused performance merely because it appears in the
winner. If a dimension shows no clear difference, say so.
"""

PROMPT_COHORT_SYNTHESIS = """Prompt 4 — COHORT SYNTHESIS (run last)

From the pair comparisons, propose findings in EXACTLY this schema, one block
per finding. Only patterns appearing in >=3 matched pairs qualify; everything
else goes under `weak_signals` at the end.

finding_id: (snake_case)
hypothesis: (one sentence)
finding_type: correlational
matched_pairs_examined: (count)
winner_frequency: (0-1)
control_frequency: (0-1)
supporting_pairs: (winner_id + control_id + <=20-word evidence + timestamps)
counterexamples: (winners lacking the trait / controls having it)
alternative_explanations: (at least one)
confidence: low / medium / high
reusable_rule: (mechanism-level writing rule, never a copyable sentence)
do_not_copy: (specific phrasings/stories this rule must not import)

Also answer separately:
A. CONTENT GAPS - questions raised but never answered in depth in any source.
B. NEGATIVE SPACE - retiree concerns (scams, SS, taxes, health costs,
   housing) appearing in NO source.
C. AUDIENCE VOCABULARY - exact pain phrases hosts use for 60-75 viewers.
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--channel", default="senior_wealth_us")
    args = parser.parse_args()

    res = ROOT / "output" / "research" / args.channel
    packet = json.loads((res / "cohort_packet.json").read_text(encoding="utf-8"))
    channel_cfg = json.loads((ROOT / "channels" / f"{args.channel}.json")
                             .read_text(encoding="utf-8"))

    pilot = res / "notebooklm" / "pilot"
    (pilot / "sources").mkdir(parents=True, exist_ok=True)
    (pilot / "prompts").mkdir(parents=True, exist_ok=True)
    tmp = res / "notebooklm" / "_vtt_tmp"
    tmp.mkdir(parents=True, exist_ok=True)

    control_of = {c["matched_to"]: c["video_id"] for c in packet["controls"]
                  if c.get("matched_to")}
    videos = packet["winners"] + packet["controls"]

    manifest_rows: list[dict] = []
    csv_lines = ["video_id,role,channel,outlier_ratio,matched_control,packet_file"]
    ok = 0
    for v in videos:
        vid = v["video_id"]
        vtt = fetch_vtt(vid, tmp)
        if vtt:
            transcript = vtt_to_timestamped_text(vtt)
            method = "youtube_captions_via_yt_dlp (timestamped)"
        else:
            # Fall back to the flat cohort transcript so the packet still ships.
            flat = res / "transcripts" / f"{v['role']}_{vid}.txt"
            transcript = (flat.read_text(encoding="utf-8").split("\n\n", 1)[-1]
                          if flat.exists() else "(transcript unavailable)")
            method = "flat_cohort_transcript (no timestamps)"
        matched = control_of.get(vid, "") if v["role"] == "winner" else \
            f"(this IS the control of {v.get('matched_to', '?')})"
        body = packet_md(v, channel_cfg, transcript, matched, method)
        fname = f"{v['role']}_{v['channel_id'].lstrip('@')}_{vid}.md"
        (pilot / "sources" / fname).write_text(body, encoding="utf-8")
        manifest_rows.append({
            "video_id": vid, "role": v["role"],
            "packet_path": f"sources/{fname}",
            "source_hash": "sha256:" + hashlib.sha256(body.encode()).hexdigest(),
            "status": "exported", "uploaded": False,
        })
        csv_lines.append(f"{vid},{v['role']},{v['channel_id']},"
                         f"{v.get('outlier_ratio', '')},{matched},{fname}")
        ok += 1
        print(f"  packet {ok}/{len(videos)}: {fname} ({method.split(' ')[0]})")
        time.sleep(1.5)

    n_ch = len({v["channel_id"] for v in videos})
    (pilot / "00_research_protocol.md").write_text(PROTOCOL.format(
        n_win=len(packet["winners"]), n_ctl=len(packet["controls"]),
        n_ch=n_ch, scan_date=packet.get("scanned_at", "")[:10]), encoding="utf-8")
    (pilot / "prompts" / "1_source_audit.md").write_text(PROMPT_SOURCE_AUDIT, encoding="utf-8")
    (pilot / "prompts" / "2_video_card.md").write_text(PROMPT_VIDEO_CARD, encoding="utf-8")
    (pilot / "prompts" / "3_pair_comparison.md").write_text(PROMPT_PAIR_COMPARISON, encoding="utf-8")
    (pilot / "prompts" / "4_cohort_synthesis.md").write_text(PROMPT_COHORT_SYNTHESIS, encoding="utf-8")
    (pilot / "00_manifest.csv").write_text("\n".join(csv_lines), encoding="utf-8")
    (pilot / "corpus_manifest.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in manifest_rows) + "\n",
        encoding="utf-8")

    print(f"\nPILOT EXPORTED: {ok} packets + protocol + 4 prompts -> {pilot}")
    print("Upload: NotebookLM > new notebook > Add source > choose ALL files in "
          "sources/ + 00_research_protocol.md (multi-select, one shot).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
