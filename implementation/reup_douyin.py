"""CLI for the Douyin → Vietnamese reup pipeline.

    python reup_douyin.py run "https://v.douyin.com/xxxxx/"
    python reup_douyin.py run "<url>" --stop-after translate   # inspect before paying for TTS
    python reup_douyin.py jobs
    python reup_douyin.py voices
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

DEFAULT_WORKSPACE = Path(__file__).resolve().parent / "output" / "reup"

STAGES = (
    "bootstrap", "probe", "extract_audio", "asr", "translate",
    "subtitles", "tts", "voice_track", "mixdown", "export",
)


def _cmd_run(args: argparse.Namespace) -> int:
    from omnicast.reup.runner import ReupError, build_reup_settings, run_reup_job

    cookies: dict[str, str] = {}
    if args.cookies:
        cookie_path = Path(args.cookies)
        if cookie_path.is_file():
            cookies = json.loads(cookie_path.read_text(encoding="utf-8"))
        else:
            # "k=v; k2=v2" straight from the browser devtools Cookie header
            for part in args.cookies.split(";"):
                if "=" in part:
                    key, value = part.split("=", 1)
                    cookies[key.strip()] = value.strip()

    def on_stage(stage: str, detail: str) -> None:
        print(f"  [{stage:<13}] {detail}", flush=True)

    try:
        settings = build_reup_settings(
            asr_model=args.asr_model,
            translation_model=args.translation_model,
        )
        resume_root = Path(args.resume).expanduser() if args.resume else None
        if resume_root is not None and not resume_root.is_absolute():
            # Accept a bare aweme id as shorthand for its workspace folder.
            resume_root = Path(args.workspace) / resume_root
        result = run_reup_job(
            args.url,
            workspace_root=Path(args.workspace),
            resume_project_root=resume_root,
            translation_backend=args.backend,
            cookies=cookies,
            proxy=args.proxy or "",
            settings=settings,
            voice_preset_id=args.voice_preset,
            voice_id=args.voice,
            export_preset_id=args.export_preset,
            stop_after=args.stop_after,
            channel_id=args.channel,
            allow_pending_review=args.force,
            max_audio_speed=None if args.no_rate_align else args.max_audio_speed,
            on_stage=on_stage,
        )
    except ReupError as exc:
        print(f"\nFAILED: {exc}", file=sys.stderr)
        return 1

    print("\n--- done ---")
    print(f"  project    : {result.project_root}")
    print(f"  segments   : {result.segment_count}")
    print(f"  stages     : {' -> '.join(result.stages_run)}")
    if result.subtitle_paths:
        for path in result.subtitle_paths:
            print(f"  subtitle   : {path}")
    if result.mixed_audio:
        print(f"  mixed audio: {result.mixed_audio}")
    if result.exported_video:
        print(f"  video      : {result.exported_video}")
    if result.needs_review:
        print(f"\n  {result.review_pending} segment(s) flagged for human review "
              f"— check before publishing.")
    return 0


def _cmd_capcut(args: argparse.Namespace) -> int:
    """Write a CapCut draft, or read back the speech CapCut generated for one."""
    from omnicast.reup.capcut.draft import (
        CAPCUT_DRAFT_ROOT, CapCutDraftError, SubtitleLine,
        list_drafts, read_generated_audio, write_draft,
    )
    from omnicast.reup.project.database import ProjectDatabase

    if args.action == "drafts":
        for draft in list_drafts():
            print(f"  {draft.name}")
        return 0

    if args.action == "srt":
        # CapCut imports subtitles via Text -> Local captions, which is far more
        # reliable than hand-built text layers. Always the ORIGINAL timings:
        # OmniCast does its own retiming after the audio comes back, so a
        # stretched SRT would be retimed twice.
        project = Path(args.project or "")
        if not project.is_absolute():
            project = Path(args.workspace) / project
        database = ProjectDatabase(project / "project.db")
        project_id = database.get_project()["project_id"]
        track = database.get_active_subtitle_track(project_id)
        rows = database.list_subtitle_events(project_id, track_id=str(track["track_id"]))

        def _stamp(ms: int) -> str:
            s, ms = divmod(int(ms), 1000)
            m, s = divmod(s, 60)
            h, m = divmod(m, 60)
            return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

        out = project / "exports" / f"{args.name}.srt"
        out.parent.mkdir(parents=True, exist_ok=True)
        blocks = []
        for i, r in enumerate(rows, 1):
            text = (r["tts_text"] or r["text"] or "").strip()
            if not text:
                continue
            stamps = f"{_stamp(r['start_ms'])} --> {_stamp(r['end_ms'])}"
            blocks.append("\n".join([str(i), stamps, text, ""]))
        out.write_text("\n".join(blocks), encoding="utf-8")
        print(f"  {out}")
        print(f"  {len(blocks)} dòng")
        print()
        print("  CapCut -> Text -> Local captions -> chọn file này")
        print("  rồi chọn hết caption -> Text to speech -> Generate speech")
        return 0

    if args.action == "read":
        result = read_generated_audio(CAPCUT_DRAFT_ROOT / args.name)
        print(f"  {len(result.clips)} clip đã sinh")
        for clip in result.clips[:10]:
            print(f"   #{clip.segment_index:<4} {clip.duration_ms:>6}ms  {clip.audio_path.name}")
        if result.unmatched:
            print(f"  {len(result.unmatched)} clip không map được / thiếu file")
        return 0 if result.clips else 1

    # action == "write"
    project = Path(args.project)
    if not project.is_absolute():
        project = Path(args.workspace) / project
    database = ProjectDatabase(project / "project.db")
    project_id = database.get_project()["project_id"]
    track = database.get_active_subtitle_track(project_id)
    rows = database.list_subtitle_events(project_id, track_id=str(track["track_id"]))
    lines = [
        SubtitleLine(i, int(r["start_ms"]), int(r["end_ms"]),
                     (r["tts_text"] or r["text"] or "").strip())
        for i, r in enumerate(rows)
    ]

    templates = list_drafts()
    if not templates:
        print("Chưa có project CapCut nào để làm mẫu — tạo một project bất kỳ trong "
              "CapCut (có ít nhất 1 lớp text) rồi chạy lại.", file=sys.stderr)
        return 1
    template = CAPCUT_DRAFT_ROOT / args.template if args.template else templates[0]

    try:
        result = write_draft(lines, template_draft=template, name=args.name)
    except CapCutDraftError as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 1

    print(f"  draft: {result.draft_dir}")
    print(f"  {result.line_count} dòng, {result.duration_ms/1000:.0f}s")
    print()
    print("  Mở CapCut -> chọn hết text -> Text to speech -> chọn giọng -> Generate speech")
    print(f"  Xong chạy: python reup_douyin.py capcut read --name \"{args.name}\"")
    return 0


def _cmd_jobs(args: argparse.Namespace) -> int:
    from omnicast.reup import vault_link

    rows = vault_link.list_jobs(status=args.status, limit=args.limit)
    if not rows:
        print("(no reup jobs recorded)")
        return 0
    print(f"{'job_id':<20} {'status':<9} {'stage':<13} {'review':>6}  title")
    for row in rows:
        title = (row.title or row.source_url)[:52]
        print(f"{row.job_id:<20} {row.status:<9} {(row.last_stage or '-'):<13} "
              f"{row.review_pending:>6}  {title}")
    return 0


def _cmd_voices(_: argparse.Namespace) -> int:
    from omnicast.media.providers.registry import get_tts_provider

    provider = get_tts_provider("vieneu")
    print(f"{provider.name} — {len(provider.models)} preset voices\n")
    for model in provider.models:
        print(f"  vieneu:{model.id:<14} {model.description}")
    print("\nClone a custom voice by dropping <name>.wav + <name>.txt into the")
    print("project's assets/voices/ folder.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="download, translate and dub one Douyin video")
    run.add_argument("url", help="Douyin share link or www.douyin.com/video/<id>")
    run.add_argument("--workspace", default=str(DEFAULT_WORKSPACE))
    run.add_argument("--voice-preset", default="vieneu-default-vi")
    run.add_argument("--voice", metavar="NAME", default="Mai Anh",
                     help="VieNeu voice name, e.g. \"Mai Anh\" (see: reup_douyin.py voices)")
    run.add_argument("--export-preset", default="youtube-16x9",
                     help="youtube-16x9 | shorts-9x16")
    run.add_argument("--stop-after", choices=STAGES,
                     help="stop once this stage finishes")
    run.add_argument("--asr-model", default="small",
                     help="faster-whisper size: tiny/base/small/medium/large-v3")
    run.add_argument("--translation-model", default="gpt-4.1-mini")
    run.add_argument("--backend", default="claude-cli",
                     choices=("claude-cli", "groq", "openai"),
                     help="translation engine; claude-cli costs no API credit")
    run.add_argument("--resume", metavar="AWEME_ID_OR_PATH",
                     help="continue an existing project instead of downloading again")
    run.add_argument("--max-audio-speed", type=float, default=1.2,
                     help="cap on voice speed-up; the rest is absorbed by stretching "
                          "the video (default 1.2, upstream pyvideotrans threshold)")
    run.add_argument("--no-rate-align", action="store_true",
                     help="old behaviour: squeeze each line into its original slot")
    run.add_argument("--force", action="store_true",
                     help="dub/export even with lines still awaiting review")
    run.add_argument("--cookies", help="path to a cookie JSON file, or a raw Cookie header")
    run.add_argument("--proxy", help="http(s) proxy for the download")
    run.add_argument("--channel", help="OmniCast channel id to attribute the job to")
    run.set_defaults(func=_cmd_run)

    jobs = sub.add_parser("jobs", help="list reup jobs recorded in vault.db")
    jobs.add_argument("--status", choices=("pending", "running", "done", "review", "failed"))
    jobs.add_argument("--limit", type=int, default=25)
    jobs.set_defaults(func=_cmd_jobs)

    capcut = sub.add_parser("capcut", help="CapCut draft bridge (real CapCut voices)")
    capcut.add_argument("action", choices=("srt", "write", "read", "drafts"))
    capcut.add_argument("--project", help="reup project (aweme id or path) to take subtitles from")
    capcut.add_argument("--workspace", default=str(DEFAULT_WORKSPACE))
    capcut.add_argument("--name", default="OmniCast_Reup", help="draft name to create/read")
    capcut.add_argument("--template", help="existing CapCut project to copy the shape from")
    capcut.set_defaults(func=_cmd_capcut)

    voices = sub.add_parser("voices", help="list available Vietnamese voices")
    voices.set_defaults(func=_cmd_voices)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
