"""Write translated subtitles into a CapCut draft, and read its TTS back.

CapCut's Vietnamese voices only exist on ByteDance's servers, so the one clean
way to use them is to let CapCut do the synthesis: OmniCast writes the
Vietnamese lines into a draft, the operator opens it and hits *Generate speech*
with the voice they want, and OmniCast reads the produced audio back and
carries on with retiming, mixing and export.

Drafts are not built from scratch here. The format is large, undocumented and
version-specific (`draft_content.json` runs to thousands of lines for a single
text layer), so an existing draft is used as a template and only its text
material/segments are replaced. That keeps every field CapCut expects — fonts,
styles, canvas, render indices — exactly as the installed version wrote them.

Timeranges in the draft are microseconds.
"""

from __future__ import annotations

import json
import shutil
import uuid
from dataclasses import dataclass, field
from pathlib import Path

MS_TO_US = 1000

CAPCUT_DRAFT_ROOT = (
    Path.home()
    / "AppData"
    / "Local"
    / "CapCut"
    / "User Data"
    / "Projects"
    / "com.lveditor.draft"
)
TTS_CACHE_DIR = (
    Path.home() / "AppData" / "Local" / "CapCut" / "User Data" / "Cache" / "tts"
)

AUDIO_SUFFIXES = (".wav", ".mp3", ".m4a", ".aac", ".flac")


class CapCutDraftError(RuntimeError):
    """Raised when a draft cannot be written or read back."""


@dataclass(slots=True)
class SubtitleLine:
    segment_index: int
    start_ms: int
    end_ms: int
    text: str


@dataclass(slots=True)
class DraftWriteResult:
    draft_dir: Path
    line_count: int
    duration_ms: int


@dataclass(slots=True)
class GeneratedClip:
    segment_index: int
    audio_path: Path
    duration_ms: int


@dataclass(slots=True)
class DraftReadResult:
    draft_dir: Path
    clips: list[GeneratedClip] = field(default_factory=list)
    unmatched: list[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.clips


def list_drafts(root: Path | None = None) -> list[Path]:
    """Every CapCut project folder, newest first."""
    base = root or CAPCUT_DRAFT_ROOT
    if not base.is_dir():
        return []
    drafts = [
        d
        for d in base.iterdir()
        if d.is_dir() and (d / "draft_content.json").is_file()
    ]
    return sorted(drafts, key=lambda d: d.stat().st_mtime, reverse=True)


def _new_id() -> str:
    return str(uuid.uuid4()).upper()


def _clone_text_material(template: dict, text: str) -> dict:
    """Copy a text material, swapping only the words.

    `content` is itself a JSON document carrying the text plus its style runs;
    replacing the whole thing would drop the font path and colours CapCut wrote.
    """
    material = json.loads(json.dumps(template))
    material["id"] = _new_id()
    try:
        content = json.loads(material.get("content") or "{}")
    except (TypeError, ValueError):
        content = {}
    content["text"] = text
    # Style runs carry character ranges; a stale range past the end of a
    # shorter line makes CapCut drop the styling for the whole layer.
    for style in content.get("styles") or []:
        style["range"] = [0, len(text)]
    material["content"] = json.dumps(content, ensure_ascii=False)
    material["base_content"] = text
    return material


def _clone_text_segment(
    template: dict,
    material_id: str,
    line: SubtitleLine,
    extra_materials: dict[str, tuple[str, dict]] | None = None,
    materials: dict | None = None,
) -> dict:
    segment = json.loads(json.dumps(template))
    segment["id"] = _new_id()
    segment["material_id"] = material_id
    segment["target_timerange"] = {
        "start": line.start_ms * MS_TO_US,
        "duration": max(1, line.end_ms - line.start_ms) * MS_TO_US,
    }
    # Every segment copied from one template would otherwise share the
    # template's `extra_material_refs` — typically a single `sticker_animation`
    # entry. CapCut treats a text clip whose per-segment materials are owned by
    # another clip as not fully formed, and refuses to run *Generate speech* on
    # it ("This text does not support text-to-speech"). Give each clip its own.
    if extra_materials is not None and materials is not None:
        fresh_refs = []
        for ref in segment.get("extra_material_refs") or []:
            source = extra_materials.get(str(ref))
            if source is None:
                fresh_refs.append(ref)
                continue
            category, material = source
            clone = json.loads(json.dumps(material))
            clone["id"] = _new_id()
            materials.setdefault(category, []).append(clone)
            fresh_refs.append(clone["id"])
        segment["extra_material_refs"] = fresh_refs
    return segment


def write_draft(
    lines: list[SubtitleLine],
    *,
    template_draft: Path,
    name: str,
    root: Path | None = None,
) -> DraftWriteResult:
    """Create a CapCut draft whose text track is `lines`.

    `template_draft` must be an existing project from the same CapCut version —
    its text material and segment are used as the shape for every new line.
    """
    if not lines:
        raise CapCutDraftError("No subtitle lines to write")

    template_content = template_draft / "draft_content.json"
    if not template_content.is_file():
        raise CapCutDraftError(f"Template draft has no draft_content.json: {template_draft}")

    document = json.loads(template_content.read_text(encoding="utf-8"))
    text_materials = document.get("materials", {}).get("texts") or []
    text_tracks = [t for t in document.get("tracks", []) if t.get("type") == "text"]
    if not text_materials or not text_tracks:
        raise CapCutDraftError(
            "Template draft needs at least one text layer to copy its shape from"
        )

    material_template = text_materials[0]
    segment_template = text_tracks[0].get("segments", [{}])[0]

    # id -> (category, material), so a segment's extra refs can be cloned along
    # with it rather than shared across every line.
    materials_by_id: dict[str, tuple[str, dict]] = {
        str(item["id"]): (category, item)
        for category, items in document.get("materials", {}).items()
        if isinstance(items, list)
        for item in items
        if isinstance(item, dict) and item.get("id")
    }

    new_materials: list[dict] = []
    new_segments: list[dict] = []
    for line in sorted(lines, key=lambda item: item.start_ms):
        text = (line.text or "").strip()
        if not text:
            continue
        material = _clone_text_material(material_template, text)
        new_materials.append(material)
        new_segments.append(
            _clone_text_segment(
                segment_template,
                material["id"],
                line,
                materials_by_id,
                document["materials"],
            )
        )

    if not new_segments:
        raise CapCutDraftError("Every subtitle line was empty")

    document["materials"]["texts"] = new_materials
    text_tracks[0]["segments"] = new_segments
    document["id"] = _new_id()
    duration_ms = max(line.end_ms for line in lines)
    document["duration"] = max(int(document.get("duration") or 0), duration_ms * MS_TO_US)

    target_root = root or CAPCUT_DRAFT_ROOT
    draft_dir = target_root / name
    if draft_dir.exists():
        raise CapCutDraftError(f"Draft already exists: {draft_dir}")

    # Copy the template folder so sidecar files CapCut expects come along, then
    # overwrite the content. `.locked` would make CapCut think the project is
    # open in another window.
    shutil.copytree(
        template_draft,
        draft_dir,
        ignore=shutil.ignore_patterns(".locked", "*.tmp", "*.bak"),
    )
    (draft_dir / "draft_content.json").write_text(
        json.dumps(document, ensure_ascii=False), encoding="utf-8"
    )

    return DraftWriteResult(
        draft_dir=draft_dir, line_count=len(new_segments), duration_ms=duration_ms
    )


def read_generated_audio(draft_dir: Path) -> DraftReadResult:
    """Collect the audio CapCut produced for a draft's text track.

    After *Generate speech*, CapCut adds audio materials whose paths point at
    files it downloaded. Matching is by timeline position: the audio segment
    that starts where line N starts belongs to line N.
    """
    content_path = draft_dir / "draft_content.json"
    if not content_path.is_file():
        raise CapCutDraftError(f"No draft_content.json in {draft_dir}")

    document = json.loads(content_path.read_text(encoding="utf-8"))
    audio_materials = {
        str(m.get("id")): m for m in (document.get("materials", {}).get("audios") or [])
    }
    if not audio_materials:
        return DraftReadResult(draft_dir=draft_dir)

    # Text segment start -> line index, so audio can be matched by position.
    text_starts: dict[int, int] = {}
    for track in document.get("tracks", []):
        if track.get("type") != "text":
            continue
        for index, segment in enumerate(track.get("segments", [])):
            start = int((segment.get("target_timerange") or {}).get("start", 0))
            text_starts[start] = index

    clips: list[GeneratedClip] = []
    unmatched: list[str] = []
    for track in document.get("tracks", []):
        if track.get("type") != "audio":
            continue
        for segment in track.get("segments", []):
            material = audio_materials.get(str(segment.get("material_id")))
            if not material:
                continue
            raw_path = str(material.get("path") or "")
            if not raw_path or not raw_path.lower().endswith(AUDIO_SUFFIXES):
                continue
            audio_path = Path(raw_path)
            if not audio_path.is_file():
                unmatched.append(raw_path)
                continue
            timerange = segment.get("target_timerange") or {}
            start = int(timerange.get("start", 0))
            index = text_starts.get(start)
            if index is None:
                unmatched.append(raw_path)
                continue
            clips.append(
                GeneratedClip(
                    segment_index=index,
                    audio_path=audio_path,
                    duration_ms=int(timerange.get("duration", 0)) // MS_TO_US,
                )
            )

    clips.sort(key=lambda c: c.segment_index)
    return DraftReadResult(draft_dir=draft_dir, clips=clips, unmatched=unmatched)
