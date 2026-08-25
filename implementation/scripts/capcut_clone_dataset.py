"""Build a Vietnamese voice-clone dataset out of CapCut's own TTS voices.

The three voices the operator wants — *Cô Gái Hoạt Ngôn*, *Nguồn nhỏ ngọt
ngào*, *Thanh niên Tự Tin* — live on ByteDance's servers. OmniCast does not
call the unofficial CapCut/TikTok speech endpoints (see
``media/capcut_voices.py``), so synthesis is handed to the installed CapCut
app: this script writes the sentences into a draft, the operator hits
*Generate speech* once per draft, and the script reads the produced audio back
out, normalises it and writes the label files GPT-SoVITS / F5-TTS expect.

    python scripts/capcut_clone_dataset.py draft   --voice co_gai_hoat_ngon
    #   … open the draft in CapCut, select every text clip, Generate speech …
    python scripts/capcut_clone_dataset.py collect --voice co_gai_hoat_ngon

``collect`` is idempotent: run it again after fixing a few clips in CapCut and
only the changed files are rewritten.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

IMPL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(IMPL_ROOT / "src"))

from omnicast.reup.capcut.draft import (  # noqa: E402
    AUDIO_SUFFIXES,
    CAPCUT_DRAFT_ROOT,
    CapCutDraftError,
    SubtitleLine,
    list_drafts,
    read_generated_audio,
    write_draft,
)

DATASET_ROOT = IMPL_ROOT / "output" / "voice_clone"

# Slug -> the label CapCut shows in its Vietnamese voice list. The slug is what
# ends up in train.list as the speaker name, so keep it ascii and stable.
VOICES: dict[str, dict[str, str]] = {
    "co_gai_hoat_ngon": {
        "label": "Cô Gái Hoạt Ngôn",
        "voice_type": "BV074_streaming",
        "gender": "female",
        "note": "giọng nữ trẻ, hoạt ngôn — giọng chính",
    },
    "nguon_nho_ngot_ngao": {
        "label": "Nhỏ Ngọt Ngào",
        "voice_type": "BV421_vivn_streaming",
        "gender": "female",
        "note": "giọng nữ ngọt, có nhãn Free trong CapCut",
    },
    "thanh_nien_tu_tin": {
        "label": "Thanh Niên Tự Tin",
        "voice_type": "BV075_streaming",
        "gender": "male",
        "note": "giọng nam trẻ, tự tin",
    },
}

# The CapCut editor API client lives in _refs (read-only reference checkout).
CAPCUT_SDK_PATH = IMPL_ROOT.parent / "_refs" / "capcut-tts-api"

DEFAULT_SCRIPT = IMPL_ROOT / "assets" / "voice_clone" / "vi_200_lines.txt"

# Timeline slot per line. CapCut drops the generated audio at the text clip's
# start, so the slot only has to be long enough that neighbouring clips do not
# pile up — being generous costs nothing but timeline length.
MS_PER_CHAR = 72
SLOT_PADDING_MS = 900
SLOT_MIN_MS = 2200
SLOT_GAP_MS = 600

TARGET_SR = 24_000
# Trim dead air at both ends but leave a short breath so the model does not
# learn to start mid-phoneme.
TRIM_THRESHOLD_DB = -45
KEEP_SILENCE_S = 0.06

# QC bounds, in ms per character of transcript. Anything outside means CapCut
# read the wrong line, cut it off, or glued two clips together.
QC_MIN_MS_PER_CHAR = 28
QC_MAX_MS_PER_CHAR = 150
QC_FLOOR_MS = 400


class ToolError(RuntimeError):
    pass


# ── helpers ──────────────────────────────────────────────────────────────────


def load_sentences(path: Path) -> list[str]:
    if not path.is_file():
        raise ToolError(f"Không thấy file kịch bản: {path}")
    lines = [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines()]
    return [ln for ln in lines if ln]


def dataset_dir(voice: str) -> Path:
    return DATASET_ROOT / voice


def slot_ms(text: str) -> int:
    return max(SLOT_MIN_MS, len(text) * MS_PER_CHAR + SLOT_PADDING_MS)


def pick_template(explicit: Path | None) -> Path:
    """A draft from the installed CapCut version to copy the text layer's shape from."""
    if explicit:
        if not (explicit / "draft_content.json").is_file():
            raise ToolError(f"Template không hợp lệ (thiếu draft_content.json): {explicit}")
        return explicit

    candidates: list[tuple[int, Path]] = []
    for draft in list_drafts():
        if draft.name.startswith("VC_"):
            continue  # our own output, not a template
        try:
            doc = json.loads((draft / "draft_content.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        texts = doc.get("materials", {}).get("texts") or []
        text_tracks = [t for t in doc.get("tracks", []) if t.get("type") == "text"]
        if not texts or not text_tracks or not text_tracks[0].get("segments"):
            continue
        candidates.append((len(text_tracks[0]["segments"]), draft))

    if not candidates:
        raise ToolError(
            "Không tìm thấy draft CapCut nào có sẵn lớp text để làm template.\n"
            "Mở CapCut, tạo 1 project, thêm 1 dòng text bất kỳ, lưu rồi chạy lại."
        )
    # Fewest segments = cheapest to copy and least stale state to inherit.
    candidates.sort(key=lambda item: item[0])
    return candidates[0][1]


def patch_draft_meta(draft_dir: Path) -> None:
    """Point the copied meta file at its new folder.

    `write_draft` copies the template wholesale, so the new project would
    otherwise show up in CapCut carrying the template's name and path.
    """
    meta_path = draft_dir / "draft_meta_info.json"
    if not meta_path.is_file():
        return
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    meta["draft_name"] = draft_dir.name
    meta["draft_fold_path"] = str(draft_dir).replace("\\", "/")
    meta["draft_id"] = draft_dir.name.upper()
    meta_path.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")


def strip_media_tracks(draft_dir: Path, text_end_ms: int) -> int:
    """Drop everything but the text track from a freshly written draft.

    The template is a real project, so it drags its footage along — here that
    was a 39-minute Douyin file on another drive. Nothing but the text clips
    matters for *Generate speech*, and an offline media reference just makes
    CapCut slow to open and noisy about it. Only the tracks are removed; the
    orphaned materials stay, because other entries still point into them.
    """
    content_path = draft_dir / "draft_content.json"
    document = json.loads(content_path.read_text(encoding="utf-8"))
    tracks = document.get("tracks", [])
    kept = [t for t in tracks if t.get("type") == "text"]
    removed = len(tracks) - len(kept)
    document["tracks"] = kept
    document["duration"] = text_end_ms * 1000
    content_path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    return removed


def match_by_nearest_start(draft_dir: Path, tolerance_ms: int = 400) -> dict[int, Path]:
    """Fallback matcher: audio segment -> nearest text segment start.

    `read_generated_audio` requires the audio to start on exactly the same
    microsecond as its text clip. That holds when CapCut drops speech straight
    onto the text, but a nudged clip or a rounding difference silently turns
    into an unmatched file. Here the nearest text start within a tolerance
    wins, and each line can only be claimed once.
    """
    document = json.loads((draft_dir / "draft_content.json").read_text(encoding="utf-8"))
    audio_materials = {
        str(m.get("id")): m for m in (document.get("materials", {}).get("audios") or [])
    }
    text_starts: list[tuple[int, int]] = []
    for track in document.get("tracks", []):
        if track.get("type") != "text":
            continue
        for index, segment in enumerate(track.get("segments", [])):
            text_starts.append((int((segment.get("target_timerange") or {}).get("start", 0)), index))
    if not text_starts:
        return {}

    candidates: list[tuple[int, int, Path]] = []  # (distance, line_index, path)
    for track in document.get("tracks", []):
        if track.get("type") != "audio":
            continue
        for segment in track.get("segments", []):
            material = audio_materials.get(str(segment.get("material_id")))
            if not material:
                continue
            raw_path = str(material.get("path") or "")
            if not raw_path.lower().endswith(AUDIO_SUFFIXES) or not Path(raw_path).is_file():
                continue
            start = int((segment.get("target_timerange") or {}).get("start", 0))
            distance, index = min(
                ((abs(start - ts) // 1000, idx) for ts, idx in text_starts),
                key=lambda pair: pair[0],
            )
            if distance <= tolerance_ms:
                candidates.append((distance, index, Path(raw_path)))

    # Closest match wins each line, so a stray clip cannot displace a exact hit.
    matched: dict[int, Path] = {}
    for distance, index, path in sorted(candidates, key=lambda c: c[0]):
        matched.setdefault(index, path)
    return matched


def ffprobe_duration_ms(path: Path) -> int:
    out = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=nw=1:nk=1", str(path),
        ],
        capture_output=True, text=True,
    )
    try:
        return int(float(out.stdout.strip()) * 1000)
    except ValueError:
        return 0


def normalise_clip(src: Path, dest: Path) -> None:
    """CapCut cache file -> mono 16-bit WAV at the training sample rate, trimmed."""
    trim = (
        f"silenceremove=start_periods=1:start_silence={KEEP_SILENCE_S}"
        f":start_threshold={TRIM_THRESHOLD_DB}dB,"
        "areverse,"
        f"silenceremove=start_periods=1:start_silence={KEEP_SILENCE_S}"
        f":start_threshold={TRIM_THRESHOLD_DB}dB,"
        "areverse"
    )
    dest.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error", "-i", str(src),
            "-af", trim, "-ac", "1", "-ar", str(TARGET_SR),
            "-sample_fmt", "s16", str(dest),
        ],
        capture_output=True, text=True,
    )
    if result.returncode != 0 or not dest.is_file():
        raise ToolError(f"ffmpeg lỗi khi xử lý {src.name}: {result.stderr.strip()[:200]}")


# ── commands ─────────────────────────────────────────────────────────────────


@dataclass(slots=True)
class PartPlan:
    draft_name: str
    first_index: int  # 1-based index into the full sentence list
    texts: list[str]


def cmd_draft(args: argparse.Namespace) -> int:
    voice = args.voice
    sentences = load_sentences(Path(args.script) if args.script else DEFAULT_SCRIPT)
    template = pick_template(Path(args.template) if args.template else None)
    print(f"[template] {template.name}  ({len(sentences)} câu)")

    parts = max(1, args.parts)
    per_part = -(-len(sentences) // parts)
    plans: list[PartPlan] = []
    for p in range(parts):
        chunk = sentences[p * per_part : (p + 1) * per_part]
        if not chunk:
            continue
        suffix = f"_p{p + 1}" if parts > 1 else ""
        plans.append(PartPlan(f"VC_{voice}{suffix}", p * per_part + 1, chunk))

    out_dir = dataset_dir(voice)
    out_dir.mkdir(parents=True, exist_ok=True)

    written = []
    for plan in plans:
        draft_path = CAPCUT_DRAFT_ROOT / plan.draft_name
        if draft_path.exists():
            if not args.force:
                raise ToolError(
                    f"Draft đã tồn tại: {draft_path}\n"
                    f"Dùng --force để ghi đè (sẽ mất TTS đã tạo trong draft đó)."
                )
            shutil.rmtree(draft_path)

        lines: list[SubtitleLine] = []
        cursor = 0
        for offset, text in enumerate(plan.texts):
            dur = slot_ms(text)
            lines.append(SubtitleLine(offset, cursor, cursor + dur, text))
            cursor += dur + SLOT_GAP_MS

        result = write_draft(lines, template_draft=template, name=plan.draft_name)
        patch_draft_meta(result.draft_dir)
        if not args.keep_media:
            removed = strip_media_tracks(result.draft_dir, result.duration_ms)
            if removed:
                print(f"[clean ] {plan.draft_name}: bỏ {removed} track media của template")
        written.append(
            {
                "draft_name": plan.draft_name,
                "draft_dir": str(result.draft_dir),
                "first_index": plan.first_index,
                "count": result.line_count,
            }
        )
        print(
            f"[draft ] {plan.draft_name}: {result.line_count} câu, "
            f"timeline {result.duration_ms / 60000:.1f} phút"
        )

    (out_dir / "plan.json").write_text(
        json.dumps(
            {
                "voice": voice,
                "capcut_label": VOICES.get(voice, {}).get("label", voice),
                "script": str(Path(args.script) if args.script else DEFAULT_SCRIPT),
                "sentences": sentences,
                "parts": written,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    label = VOICES.get(voice, {}).get("label", voice)
    print()
    print("Việc cần làm trong CapCut:")
    print("  1. Mở CapCut (đóng và mở lại nếu chưa thấy project mới).")
    for item in written:
        print(f"  2. Mở project '{item['draft_name']}'.")
        break
    print("  3. Ctrl+A trên track text để chọn hết clip chữ.")
    print(f"  4. Text > Text to speech (Chuyển văn bản thành giọng nói) > Tiếng Việt > '{label}'.")
    print("  5. Bấm Tạo/Generate, đợi CapCut tải xong toàn bộ audio, rồi Ctrl+S.")
    print(f"  6. Chạy: python scripts/capcut_clone_dataset.py collect --voice {voice}")
    return 0


def cmd_collect(args: argparse.Namespace) -> int:
    voice = args.voice
    out_dir = dataset_dir(voice)
    plan_path = out_dir / "plan.json"
    if not plan_path.is_file():
        raise ToolError(f"Chưa có plan.json cho giọng {voice} — chạy lệnh 'draft' trước.")
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    sentences: list[str] = plan["sentences"]

    wav_dir = out_dir / "wav"
    wav_dir.mkdir(parents=True, exist_ok=True)

    collected: dict[int, Path] = {}
    missing_drafts: list[str] = []
    for part in plan["parts"]:
        draft_dir = Path(part["draft_dir"])
        if not draft_dir.is_dir():
            missing_drafts.append(part["draft_name"])
            continue
        result = read_generated_audio(draft_dir)
        by_line = {clip.segment_index: clip.audio_path for clip in result.clips}
        if len(by_line) < part["count"]:
            # Exact-start matching missed some; retry the whole draft loosely and
            # fill only the gaps, so exact hits always take precedence.
            loose = match_by_nearest_start(draft_dir)
            recovered = {i: p for i, p in loose.items() if i not in by_line}
            if recovered:
                print(f"[fix   ] {part['draft_name']}: khớp thêm {len(recovered)} clip lệch vị trí")
                by_line.update(recovered)

        if not by_line:
            print(f"[warn  ] {part['draft_name']}: chưa có audio nào — đã bấm Generate speech chưa?")
            continue
        for line_index, audio_path in by_line.items():
            collected[part["first_index"] + line_index] = audio_path

    if missing_drafts:
        print(f"[warn  ] không tìm thấy draft: {', '.join(missing_drafts)}")
    if not collected:
        raise ToolError("Không đọc được audio nào từ CapCut. Kiểm tra bước Generate speech + Ctrl+S.")

    rows: list[dict] = []
    flagged: list[str] = []
    for index in sorted(collected):
        text = sentences[index - 1]
        dest = wav_dir / f"{index:03d}.wav"
        src = collected[index]
        if dest.is_file() and dest.stat().st_mtime >= src.stat().st_mtime:
            duration = ffprobe_duration_ms(dest)
        else:
            normalise_clip(src, dest)
            duration = ffprobe_duration_ms(dest)

        per_char = duration / max(1, len(text))
        bad = (
            duration < QC_FLOOR_MS
            or per_char < QC_MIN_MS_PER_CHAR
            or per_char > QC_MAX_MS_PER_CHAR
        )
        if bad:
            flagged.append(f"{index:03d}  {duration/1000:5.2f}s  {per_char:5.1f} ms/ký-tự  {text[:60]}")
        rows.append({"index": index, "wav": dest, "text": text, "duration_ms": duration})

    total_ms = sum(r["duration_ms"] for r in rows)
    have = {r["index"] for r in rows}
    absent = [i for i in range(1, len(sentences) + 1) if i not in have]

    write_labels(out_dir, voice, rows)

    report = [
        f"voice        : {voice} ({plan.get('capcut_label')})",
        f"câu trong kịch bản: {len(sentences)}",
        f"clip thu được     : {len(rows)}",
        f"tổng thời lượng   : {total_ms/60000:.1f} phút",
        f"trung bình / clip : {total_ms/max(1,len(rows))/1000:.2f}s",
        "",
        f"thiếu ({len(absent)}): {absent if absent else 'không'}",
        "",
        f"cần nghe lại ({len(flagged)}):",
    ]
    report += [f"  {line}" for line in flagged] or ["  không có"]
    text_report = "\n".join(report)
    (out_dir / "qc_report.txt").write_text(text_report, encoding="utf-8")
    print()
    print(text_report)
    print()
    print(f"[done  ] {wav_dir}")
    return 0


def write_labels(out_dir: Path, voice: str, rows: list[dict]) -> None:
    """train.list for GPT-SoVITS, metadata.csv for F5-TTS."""
    train_lines = []
    meta_lines = ["audio_file|text"]
    for row in rows:
        wav_path = str(row["wav"]).replace("\\", "/")
        train_lines.append(f"{wav_path}|{voice}|vi|{row['text']}")
        meta_lines.append(f"wav/{row['wav'].name}|{row['text']}")

    (out_dir / "train.list").write_text("\n".join(train_lines) + "\n", encoding="utf-8")
    (out_dir / "metadata.csv").write_text("\n".join(meta_lines) + "\n", encoding="utf-8")
    print(f"[labels] train.list ({len(train_lines)} dòng) + metadata.csv")


def _capcut_client():
    if not (CAPCUT_SDK_PATH / "capcut_tts_api").is_dir():
        raise ToolError(f"Không thấy SDK CapCut tại {CAPCUT_SDK_PATH}")
    if str(CAPCUT_SDK_PATH) not in sys.path:
        sys.path.insert(0, str(CAPCUT_SDK_PATH))
    from capcut_tts_api import CapCutClient  # noqa: PLC0415

    return CapCutClient()


def _speech_url(query_response: dict) -> str:
    """Pull the mp3 URL out of a finished task.

    The interesting part of the response is a JSON document stored as a string
    inside `payload`, so it needs a second decode.
    """
    tasks = (query_response.get("data") or {}).get("tasks") or []
    if not tasks:
        raise ToolError("Task response không có tasks")
    payload = json.loads(tasks[0].get("payload") or "{}")
    subtitles = payload.get("audio_subtitles") or []
    if not subtitles or not subtitles[0].get("speech_url"):
        raise ToolError("Task xong nhưng không có speech_url")
    return str(subtitles[0]["speech_url"])


def synthesize_one(client, text: str, voice_type: str, *, timeout: float = 90.0) -> bytes:
    """One sentence in, mp3 bytes out.

    `CapCutClient.generate_speech` is not used: it polls for status `"success"`
    while the API actually answers `"succeed"`, so it always times out on a task
    that in fact finished. Polling here keeps the working path in our hands.
    """
    import time  # noqa: PLC0415

    created = client.create_tts_task(texts=text, voice=voice_type)
    tasks = (created.get("data") or {}).get("tasks") or []
    if not tasks:
        raise ToolError(f"API không nhận task: {json.dumps(created, ensure_ascii=False)[:200]}")
    task_id, token = tasks[0]["id"], tasks[0]["token"]

    deadline = time.time() + timeout
    while time.time() < deadline:
        answer = client.query_tts_task(task_id, token)
        status = ((answer.get("data") or {}).get("tasks") or [{}])[0].get("status")
        if status in {"succeed", "success"}:
            url = _speech_url(answer)
            audio = client.session.get(url, timeout=60)
            audio.raise_for_status()
            return audio.content
        if status in {"failed", "fail"}:
            raise ToolError(f"Task lỗi: {json.dumps(answer, ensure_ascii=False)[:200]}")
        time.sleep(0.8)
    raise ToolError(f"Task quá hạn {timeout}s")


def cmd_api(args: argparse.Namespace) -> int:
    """Generate the whole corpus straight from CapCut's TTS endpoint."""
    from concurrent.futures import ThreadPoolExecutor  # noqa: PLC0415

    voice = args.voice
    voice_type = VOICES[voice]["voice_type"]
    sentences = load_sentences(Path(args.script) if args.script else DEFAULT_SCRIPT)
    out_dir = dataset_dir(voice)
    wav_dir = out_dir / "wav"
    raw_dir = out_dir / "_mp3"
    wav_dir.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)

    client = _capcut_client()
    print(f"[voice ] {voice} -> {voice_type} ({VOICES[voice]['label']}), {len(sentences)} câu")

    todo = [
        (i, text)
        for i, text in enumerate(sentences, 1)
        if args.overwrite or not (wav_dir / f"{i:03d}.wav").is_file()
    ]
    if not todo:
        print("[skip  ] đã đủ file, dùng --overwrite để làm lại")
    else:
        print(f"[start ] cần sinh {len(todo)} câu, {args.workers} luồng")

    failures: dict[int, str] = {}

    def worker(job: tuple[int, str]) -> None:
        index, text = job
        for attempt in range(1, args.retries + 1):
            try:
                mp3 = synthesize_one(client, text, voice_type)
                raw = raw_dir / f"{index:03d}.mp3"
                raw.write_bytes(mp3)
                normalise_clip(raw, wav_dir / f"{index:03d}.wav")
                print(f"  [{index:03d}] ok  {text[:52]}")
                return
            except Exception as exc:  # noqa: BLE001 — one bad sentence must not stop 199 others
                if attempt == args.retries:
                    failures[index] = str(exc)[:160]
                    print(f"  [{index:03d}] LỖI {str(exc)[:80]}")

    if todo:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            list(pool.map(worker, todo))

    rows = []
    for index, text in enumerate(sentences, 1):
        wav = wav_dir / f"{index:03d}.wav"
        if wav.is_file():
            rows.append({"index": index, "wav": wav, "text": text,
                         "duration_ms": ffprobe_duration_ms(wav)})

    write_labels(out_dir, voice, rows)
    print_qc(out_dir, voice, VOICES[voice]["label"], sentences, rows, failures)
    return 0 if len(rows) == len(sentences) else 1


def print_qc(
    out_dir: Path,
    voice: str,
    label: str,
    sentences: list[str],
    rows: list[dict],
    failures: dict[int, str] | None = None,
) -> None:
    flagged = []
    for row in rows:
        per_char = row["duration_ms"] / max(1, len(row["text"]))
        if (
            row["duration_ms"] < QC_FLOOR_MS
            or per_char < QC_MIN_MS_PER_CHAR
            or per_char > QC_MAX_MS_PER_CHAR
        ):
            flagged.append(
                f"{row['index']:03d}  {row['duration_ms']/1000:5.2f}s  "
                f"{per_char:5.1f} ms/ký-tự  {row['text'][:56]}"
            )

    total_ms = sum(r["duration_ms"] for r in rows)
    have = {r["index"] for r in rows}
    absent = [i for i in range(1, len(sentences) + 1) if i not in have]

    report = [
        f"voice             : {voice} ({label})",
        f"câu trong kịch bản: {len(sentences)}",
        f"clip thu được     : {len(rows)}",
        f"tổng thời lượng   : {total_ms/60000:.1f} phút",
        f"trung bình / clip : {total_ms/max(1,len(rows))/1000:.2f}s",
        "",
        f"thiếu ({len(absent)}): {absent if absent else 'không'}",
        "",
        f"cần nghe lại ({len(flagged)}):",
    ]
    report += [f"  {line}" for line in flagged] or ["  không có"]
    if failures:
        report += ["", f"lỗi API ({len(failures)}):"]
        report += [f"  {i:03d}: {msg}" for i, msg in sorted(failures.items())]

    text_report = "\n".join(report)
    (out_dir / "qc_report.txt").write_text(text_report, encoding="utf-8")
    print()
    print(text_report)


PIPER_SR = 22_050


def cmd_export_piper(args: argparse.Namespace) -> int:
    """Lay the dataset out the way piper training expects.

    Piper fine-tunes single-speaker VITS at 22.05kHz, and reads an LJSpeech-style
    `metadata.csv` of `id|text` next to a `wav/` directory. Our masters are
    24kHz, so they are resampled rather than left for the trainer to guess at.
    """
    voice = args.voice
    source = dataset_dir(voice)
    sentences_file = Path(args.script) if args.script else DEFAULT_SCRIPT
    sentences = load_sentences(sentences_file)

    target = Path(args.out) if args.out else source / "piper"
    wav_out = target / "wav"
    wav_out.mkdir(parents=True, exist_ok=True)

    rows: list[tuple[str, str]] = []
    skipped = 0
    for index, text in enumerate(sentences, 1):
        src = source / "wav" / f"{index:03d}.wav"
        if not src.is_file():
            skipped += 1
            continue
        dest = wav_out / f"{index:03d}.wav"
        if not dest.is_file() or args.overwrite:
            result = subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src),
                 "-ac", "1", "-ar", str(PIPER_SR), "-sample_fmt", "s16", str(dest)],
                capture_output=True, text=True,
            )
            if result.returncode != 0:
                raise ToolError(f"ffmpeg lỗi ở {src.name}: {result.stderr.strip()[:160]}")
        rows.append((f"{index:03d}", text))

    (target / "metadata.csv").write_text(
        "\n".join(f"{name}|{text}" for name, text in rows) + "\n", encoding="utf-8"
    )

    total_s = sum(ffprobe_duration_ms(wav_out / f"{n}.wav") for n, _ in rows) / 1000
    print(f"[piper ] {target}")
    print(f"         {len(rows)} clip @ {PIPER_SR}Hz mono, {total_s/60:.1f} phút"
          f"{f', bỏ qua {skipped} câu chưa có wav' if skipped else ''}")
    return 0


def cmd_export_f5(args: argparse.Namespace) -> int:
    """Package the dataset the way F5-TTS-Vietnamese's `prepare_metadata.py` reads it.

    That script globs `data/your_dataset/*.wav` and expects a `.txt` of the same
    stem beside each one. It also wants 24kHz audio, which is exactly what the
    masters already are, so the wavs are copied rather than re-encoded — every
    resample is a small loss and there is nothing to gain here.
    """
    import shutil as _shutil  # noqa: PLC0415

    voice = args.voice
    source = dataset_dir(voice)
    sentences = load_sentences(Path(args.script) if args.script else DEFAULT_SCRIPT)

    target = Path(args.out) if args.out else source / "f5_dataset"
    target.mkdir(parents=True, exist_ok=True)

    count, skipped, total_ms = 0, 0, 0
    for index, text in enumerate(sentences, 1):
        src = source / "wav" / f"{index:03d}.wav"
        if not src.is_file():
            skipped += 1
            continue
        _shutil.copyfile(src, target / f"{index:03d}.wav")
        # F5's Vietnamese pipeline lowercases text during training; matching that
        # here keeps the vocab check from flagging capitals as unseen tokens.
        (target / f"{index:03d}.txt").write_text(text.lower(), encoding="utf-8")
        total_ms += ffprobe_duration_ms(src)
        count += 1

    archive = None
    if not args.no_zip:
        archive = _shutil.make_archive(str(source / f"f5_{voice}"), "zip", root_dir=target)

    print(f"[f5    ] {target}")
    print(f"         {count} cặp wav+txt @ 24kHz, {total_ms/60000:.1f} phút"
          f"{f', thiếu {skipped} câu' if skipped else ''}")
    if archive:
        print(f"[zip   ] {archive} ({Path(archive).stat().st_size/1e6:.0f} MB)")
    return 0


def _describe(value: object) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return text if len(text) <= 110 else text[:110] + "…"


def cmd_diffref(args: argparse.Namespace) -> int:
    """Compare a hand-made CapCut text clip against one this script generated.

    CapCut accepts our drafts but silently refuses to synthesize them, and the
    app gives no reason. The difference has to be a field CapCut writes and
    `write_draft` does not, so this prints exactly that set — run it against a
    project where *Generate speech* actually produced audio.
    """
    reference = CAPCUT_DRAFT_ROOT / args.draft
    if not (reference / "draft_content.json").is_file():
        raise ToolError(f"Không thấy draft: {reference}")

    ours_name = args.ours or "VC_co_gai_hoat_ngon_p1"
    ours = CAPCUT_DRAFT_ROOT / ours_name
    if not (ours / "draft_content.json").is_file():
        raise ToolError(f"Không thấy draft do script sinh: {ours}")

    def first_text(draft: Path) -> tuple[dict, dict, dict]:
        doc = json.loads((draft / "draft_content.json").read_text(encoding="utf-8"))
        materials = {m["id"]: m for m in (doc.get("materials", {}).get("texts") or [])}
        for track in doc.get("tracks", []):
            if track.get("type") != "text":
                continue
            for segment in track.get("segments", []):
                material = materials.get(str(segment.get("material_id")))
                if material:
                    return doc, material, segment
        raise ToolError(f"Draft {draft.name} không có text clip nào")

    ref_doc, ref_mat, ref_seg = first_text(reference)
    our_doc, our_mat, our_seg = first_text(ours)

    audios = len(ref_doc.get("materials", {}).get("audios") or [])
    print(f"[ref   ] {reference.name}: {audios} audio material "
          f"({'đã chạy TTS' if audios else 'CHƯA có TTS — mẫu này không dùng được'})")
    print(f"[ours  ] {ours.name}")

    # Volatile per-clip values would drown the signal; only shape matters here.
    skip = {"id", "material_id", "content", "base_content", "target_timerange", "words",
            "current_words", "extra_material_refs", "recognize_text"}

    for label, ref_obj, our_obj in (("MATERIAL", ref_mat, our_mat), ("SEGMENT", ref_seg, our_seg)):
        missing = [k for k in ref_obj if k not in our_obj and k not in skip]
        extra = [k for k in our_obj if k not in ref_obj and k not in skip]
        changed = [
            k for k in ref_obj
            if k in our_obj and k not in skip
            and json.dumps(ref_obj[k], ensure_ascii=False, sort_keys=True)
            != json.dumps(our_obj[k], ensure_ascii=False, sort_keys=True)
        ]
        print(f"\n=== {label} ===")
        print(f"  thiếu ở bản ta ({len(missing)}):")
        for k in missing:
            print(f"    + {k} = {_describe(ref_obj[k])}")
        print(f"  thừa ở bản ta ({len(extra)}): {extra or 'không'}")
        print(f"  khác giá trị ({len(changed)}):")
        for k in changed:
            print(f"    ~ {k}")
            print(f"        capcut: {_describe(ref_obj[k])}")
            print(f"        ours  : {_describe(our_obj[k])}")
    return 0


def cmd_voices(_: argparse.Namespace) -> int:
    for slug, info in VOICES.items():
        marker = "*" if slug == "co_gai_hoat_ngon" else " "
        print(f" {marker} {slug:22s} {info['label']:22s} {info['gender']:6s} — {info['note']}")
    print("\n * = giọng chính. Chạy 'draft'/'collect' lần lượt cho từng slug.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_voices = sub.add_parser("voices", help="liệt kê 3 giọng CapCut đã cấu hình")
    p_voices.set_defaults(func=cmd_voices)

    p_draft = sub.add_parser("draft", help="ghi kịch bản thành draft CapCut")
    p_draft.add_argument("--voice", required=True, choices=list(VOICES))
    p_draft.add_argument("--script", help=f"mặc định: {DEFAULT_SCRIPT}")
    p_draft.add_argument("--template", help="draft CapCut dùng làm khuôn (mặc định: tự chọn)")
    p_draft.add_argument("--parts", type=int, default=1, help="chia thành N draft cho nhẹ CapCut")
    p_draft.add_argument("--force", action="store_true", help="ghi đè draft cùng tên")
    p_draft.add_argument(
        "--keep-media",
        action="store_true",
        help="giữ lại track video/audio của template (dùng nếu CapCut không mở được draft)",
    )
    p_draft.set_defaults(func=cmd_draft)

    p_api = sub.add_parser("api", help="sinh trọn bộ qua CapCut TTS API (không cần mở app)")
    p_api.add_argument("--voice", required=True, choices=list(VOICES))
    p_api.add_argument("--script", help=f"mặc định: {DEFAULT_SCRIPT}")
    p_api.add_argument("--workers", type=int, default=4)
    p_api.add_argument("--retries", type=int, default=3)
    p_api.add_argument("--overwrite", action="store_true", help="làm lại cả file đã có")
    p_api.set_defaults(func=cmd_api)

    p_f5 = sub.add_parser("export-f5", help="đóng gói dataset cho F5-TTS-Vietnamese (Colab)")
    p_f5.add_argument("--voice", required=True, choices=list(VOICES))
    p_f5.add_argument("--script", help=f"mặc định: {DEFAULT_SCRIPT}")
    p_f5.add_argument("--out", help="thư mục đích (mặc định <dataset>/f5_dataset)")
    p_f5.add_argument("--no-zip", action="store_true", help="không tạo file zip để upload")
    p_f5.set_defaults(func=cmd_export_f5)

    p_piper = sub.add_parser("export-piper", help="xuất dataset sang layout piper training")
    p_piper.add_argument("--voice", required=True, choices=list(VOICES))
    p_piper.add_argument("--script", help=f"mặc định: {DEFAULT_SCRIPT}")
    p_piper.add_argument("--out", help="thư mục đích (mặc định <dataset>/piper)")
    p_piper.add_argument("--overwrite", action="store_true")
    p_piper.set_defaults(func=cmd_export_piper)

    p_diff = sub.add_parser(
        "diffref", help="so text clip CapCut tự tạo (đã chạy TTS) với clip script sinh"
    )
    p_diff.add_argument("--draft", required=True, help="tên project CapCut làm tay")
    p_diff.add_argument("--ours", help="draft đối chứng (mặc định VC_co_gai_hoat_ngon_p1)")
    p_diff.set_defaults(func=cmd_diffref)

    p_collect = sub.add_parser("collect", help="đọc audio CapCut đã tạo -> dataset + nhãn")
    p_collect.add_argument("--voice", required=True, choices=list(VOICES))
    p_collect.set_defaults(func=cmd_collect)

    args = parser.parse_args()
    try:
        return args.func(args)
    except (ToolError, CapCutDraftError) as exc:
        print(f"\nLỗi: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
