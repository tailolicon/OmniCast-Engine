"""URL-first NotebookLM ingestion at cohort scale.

The pilot proved the machinery on 19 packet sources. This runs the real thing:
every discovered competitor video goes in as a YOUTUBE URL (NotebookLM pulls
the transcript itself — no download, no ASR, no packet files), in a fresh
notebook, then the research prompts run against the whole corpus.

Safety rails carried over from the pilot (operator allowlist):
  * never deletes a notebook or a source, never shares, never switches account;
  * one source at a time, failures recorded per-video for the packet fallback;
  * the manifest is the resume record — a re-run continues, never re-adds.

Usage:
  python scripts/notebooklm_scale_280.py --channel senior_wealth_us \
      [--limit 280] [--batch 40] [--headed] [--notebook-key SFR_280]
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from omnicast.analytics.notebook_research.browser_provider import (  # noqa: E402
    PROMPT_SPLIT,
    NotebookLMWorker,
    run_notebook_stage,
)
from omnicast.analytics.notebook_research.manifest import RunManifest  # noqa: E402

# Characters per chat turn. 4.6k never submitted; the 19-title prompts at
# ~2.4k always did. This sits below the proven range with room to spare —
# the cost of an extra turn is seconds, the cost of a dead send is the run.
TURN_CHAR_BUDGET = 1600


def build_prompts(winner_titles: list[str], control_titles: list[str]) -> dict[str, str]:
    """Prompts that CARRY the winner/control labels.

    First live run failed honestly: transcripts contain no view counts, so
    NotebookLM correctly refused every "compare high performers vs ordinary"
    question — it had no way to know which was which. The performance data
    lives in OUR discovery run, so it has to travel with the question.
    """
    # Present the PAIRS, so the model compares like with like. Two flat lists
    # invite it to contrast a 23-minute winner with a 6-minute control; the
    # pairing is the whole point of the design and has to survive into the
    # prompt.
    # ONE LINE PER PAIR. The three-line form pushed the cohort prompts to ~4.9k
    # characters over 86 lines, and all three failed to send — the text landed
    # in the box and nothing submitted it. The send path is hardened now, but a
    # prompt should not be near a UI's limits to begin with.
    pair_lines = [f"  P{i+1}. HIGH: {w}  ||  ORDINARY: {c}"
                  for i, (w, c) in enumerate(zip(winner_titles, control_titles))]

    # SPLIT BY CHARACTERS, NOT BY SECTION. Cutting only between the labels and
    # the task left a 4.3k first turn — still over whatever the chat box will
    # submit, since 4.6k failed and ~2.4k (the earlier 19-title prompts) always
    # worked. So the pair list itself travels in turns sized under the proven
    # range, and only the last turn asks anything.
    turns: list[str] = []
    cur: list[str] = []
    size = 0
    for line in pair_lines:
        if cur and size + len(line) > TURN_CHAR_BUDGET:
            turns.append("\n".join(cur))
            cur, size = [], 0
        cur.append(line)
        size += len(line) + 1
    if cur:
        turns.append("\n".join(cur))

    head = (
        "I am giving you the performance labels, because the transcripts do not "
        "contain view counts.\n\n"
        f"Over the next {len(turns)} message(s) I will list "
        f"{len(winner_titles)} MATCHED PAIRS. Each pair is from the SAME "
        "channel, the same format, similar length and similar publish date; the "
        "only intended difference is that HIGH earned far more views per day "
        "than ORDINARY. Reply with just OK to each list; the question comes "
        "last.\n")
    blocks = [head + PROMPT_SPLIT]
    for n, chunk in enumerate(turns, start=1):
        blocks.append(f"PAIRS {n}/{len(turns)}:\n{chunk}\nReply OK."
                      + PROMPT_SPLIT)
    label_block = "\n".join(blocks) + "\n" + (
        "Compare WITHIN each pair first, then look for patterns that repeat "
        "across pairs. Videos outside these pairs exist in the notebook but "
        "are NOT labelled — ignore them for the comparison. If a source you "
        "need is missing, say so rather than guessing.\n\n")

    return {
        "hook_shape_cohort_v3": label_block + (
            "TASK: compare how the HIGH PERFORMERS open against how the ORDINARY "
            "ones open. For each group describe the FIRST SENTENCE TYPE — an event "
            "that happened / an explicit promise of a calculation / one person's "
            "story / an abstract condition that might apply — and how long the "
            "opening runs before the first number and the first dollar figure. "
            "Quote at most 6 words from any source. Name the source title for "
            "every claim. State plainly where the evidence is thin."),
        "retention_mechanics_cohort_v3": label_block + (
            "TASK: what do the HIGH PERFORMERS do to hold attention that the "
            "ORDINARY ones do not? Look for: open loops and exactly where they are "
            "paid off, mid-video re-hooks, spoken section signposting, how the "
            "narrator reacts to their own numbers, and how often a concrete figure "
            "arrives. Give source titles. Quote at most 6 words. Where both groups "
            "do the same thing, say so — that is a genre convention, not an edge."),
        "packaging_patterns_cohort_v3": label_block + (
            "TASK: compare the TITLES of the two groups. What recurring structures "
            "appear in the high performers (deadline, rule change, first-person "
            "authority, a number, a question, a named institution) that are absent "
            "or weaker in the ordinary ones? Give the concrete patterns with the "
            "titles as evidence, and list counter-examples that break each pattern."),
    }


PROMPTS: dict[str, str] = {}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--channel", default="senior_wealth_us")
    ap.add_argument("--limit", type=int, default=280)
    ap.add_argument("--batch", type=int, default=40,
                    help="URL sources added per invocation (resume-safe)")
    ap.add_argument("--notebook-key", default="SFR_280_URL_FIRST")
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--verify-sample", type=int, default=0,
                    help="probe N sources to prove they carry transcripts "
                         "(0 = skip; ui_indexed is NOT evidence)")
    args = ap.parse_args()

    res = ROOT / "output" / "research" / args.channel
    raw = json.loads((res / "raw_videos.json").read_text(encoding="utf-8"))

    # Winner/control labels come from the cohort packet where available; every
    # other video still carries useful signal as corpus context.
    cohort_file = res / "cohort_packet.json"
    roles: dict[str, str] = {}
    if cohort_file.exists():
        packet = json.loads(cohort_file.read_text(encoding="utf-8"))
        for c in packet.get("winners", []):
            roles[c["video_id"]] = "winner"
        for c in packet.get("controls", []):
            roles[c["video_id"]] = "control"

    videos: list[tuple[str, str, str]] = []
    # The source list in the UI shows TITLES. A probe that addresses a source
    # by URL suffix asks the model to match against an index it does not have,
    # and the first live probes came back empty for exactly that reason.
    title_by_id: dict[str, str] = {}
    for _handle, items in raw.items():
        for v in items:
            vid = v.get("video_id")
            if not vid:
                continue
            if v.get("title"):
                title_by_id[vid] = v["title"]
            videos.append((vid, roles.get(vid, "corpus"),
                           f"https://www.youtube.com/watch?v={vid}"))
    videos = videos[: args.limit]

    # Performance labels travel WITH the question (see build_prompts).
    # THE LABELS COME FROM THE CURRENT COHORT, not the old pilot packet: the
    # packet holds 12 winners / 7 controls chosen by raw views, while the live
    # cohort is labelled by views/day on settled videos with matched controls.
    # Asking about the pilot's 19 titles while the notebook holds 280 sources
    # was how a "280-video analysis" stayed a 19-video analysis.
    from omnicast.analytics.cohort_labels import label_corpus, match_pairs

    # THE PROMPT MUST DESCRIBE THE PAIRS, NOT THE POOL. Listing all 32 winners
    # and all 42 controls while calling them "matched controls" overstates the
    # design: only pairs inside the duration/date calipers are matched, and
    # some winners have no acceptable control at all.
    snap = res / "corpus_snapshot.json"
    snapshot_at = (datetime.fromisoformat(
        json.loads(snap.read_text(encoding="utf-8"))["snapshot_at"])
        if snap.exists() else None)
    labelled = label_corpus(raw, now=snapshot_at)
    pair_report: dict = {}
    match_pairs(labelled, report=pair_report)
    by_id = {v.video_id: v for v in labelled}

    pairs = [(v, by_id.get(v.matched_control)) for v in labelled
             if v.role == "winner" and v.fmt == "long" and v.matched_control]
    pairs = [(w, c) for w, c in pairs if c is not None and w.title and c.title]
    win_titles = [w.title for w, _ in pairs]
    ctl_titles = [c.title for _, c in pairs]
    excluded_w = sum(1 for v in labelled if v.role == "winner"
                     and v.fmt == "long" and not v.matched_control)
    excluded_c = sum(1 for v in labelled if v.role == "control"
                     and v.fmt == "long"
                     and v.video_id not in {c.video_id for _, c in pairs})
    print(f"excluded from the prompt: {excluded_w} unpaired winners, "
          f"{excluded_c} unpaired controls (calipers "
          f"{pair_report.get('max_duration_gap_min')}min / "
          f"{pair_report.get('max_age_gap_days')}d)")
    if not win_titles or not ctl_titles:   # cohort not labelled yet → pilot packet
        packet_titles = (json.loads(cohort_file.read_text(encoding="utf-8"))
                         if cohort_file.exists()
                         else {"winners": [], "controls": []})
        win_titles = [c.get("title", "") for c in packet_titles.get("winners", [])
                      if c.get("title")]
        ctl_titles = [c.get("title", "") for c in packet_titles.get("controls", [])
                      if c.get("title")]
        print("[warn] falling back to the pilot cohort packet for labels")
    print(f"labels in prompts: {len(win_titles)} MATCHED PAIRS "
          f"(long-form, velocity-labelled, within calipers)")
    global PROMPTS
    PROMPTS = build_prompts(win_titles, ctl_titles)
    print(f"corpus: {len(videos)} videos "
          f"({sum(1 for v in videos if v[1] == 'winner')} winner / "
          f"{sum(1 for v in videos if v[1] == 'control')} control / "
          f"{sum(1 for v in videos if v[1] == 'corpus')} unlabelled)")

    base = res / "notebooklm" / "runs"
    base.mkdir(parents=True, exist_ok=True)
    manifest = RunManifest.load_or_create(base, args.channel, args.notebook_key)
    before = len(manifest.sources)
    manifest.register_url_sources(videos)
    for pid, text in PROMPTS.items():
        manifest.register_prompt(pid, text)
    manifest.save(base)
    print(f"manifest: {len(manifest.sources)} sources "
          f"(+{len(manifest.sources) - before} new), state={manifest.state}")

    profile = ROOT / "output" / "notebooklm_profile"
    if not profile.exists():
        print("REJECTED: no browser profile — run scripts/notebooklm_login.py once")
        return 1

    # THE CROSS-CHECK NEEDS THE LOCAL TRANSCRIPTS. Without this the verifier
    # falls back to an empty directory, every quote reports "no local
    # transcript", and nothing can ever reach `evidence_usable` — the probe
    # would run and prove nothing.
    vtt_dir = res / "_vtt_corpus"
    if args.verify_sample and not vtt_dir.exists():
        print(f"REJECTED: --verify-sample needs local captions at {vtt_dir}")
        return 1

    with NotebookLMWorker(profile_dir=profile, work_dir=base,
                          headless=not args.headed) as worker:
        manifest = run_notebook_stage(manifest, base, worker, PROMPTS,
                                      url_batch_limit=args.batch,
                                      verify_sample=args.verify_sample,
                                      vtt_dir=vtt_dir, titles=title_by_id)
    ev = manifest.evidence_summary()
    print(f"evidence: {ev['evidence_usable']} usable / {ev['ui_listed']} UI-listed "
          f"/ {ev['total']} total  {ev['by_status']}")
    indexed = ev["ui_listed"]
    failed = [s.video_id for s in manifest.sources if s.upload_status == "failed"]
    print(f"state={manifest.state} | indexed={indexed}/{len(manifest.sources)} "
          f"| failed={len(failed)}")
    if failed:
        print("failed ids (packet fallback candidates):", failed[:10])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
