"""Idempotent run manifest for the NotebookLM browser worker.

One JSON file per (channel, notebook_key) run, written atomically after every
state change / source upload / prompt completion, so a killed process resumes
without re-uploading sources or re-running finished prompts. This is the
memory of the state machine; the browser holds no state of its own.
"""

from __future__ import annotations

from typing import ClassVar

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field

from omnicast.analytics.notebook_research.state_machine import (
    RunState,
    advance,
    resume_point,
)


def short_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]


class SourceEntry(BaseModel):
    video_id: str
    role: str = ""
    # ONE kind per video, never both (duplicate content would inflate how
    # common a pattern looks to NotebookLM): "packet" (Markdown upload) or
    # "youtube_url" (NotebookLM pulls the transcript itself).
    source_kind: str = "packet"
    packet_path: str = ""
    url: str = ""
    source_hash: str = ""            # short hash of packet content (packet kind)
    remote_title: str = ""           # filename as it appears in the source list
    # THREE-STAGE TRUTH (operator audit 27/07). The old vocabulary stopped at
    # `indexed`, which was set for EVERY source as soon as the UI's own
    # "N sources" counter reached the expected number — a count, not a check.
    # A URL can be listed and still hold no usable transcript, and a run that
    # calls that "indexed" reports 280 pieces of evidence it never verified.
    #   pending          — registered, not yet added
    #   uploaded         — added to the notebook UI
    #   ui_indexed       — the UI counts it as a source (what we can see cheaply)
    #   transcript_verified — the notebook answered a probe about THIS source
    #   evidence_usable  — verified AND long enough to carry craft evidence
    #   failed           — add/import error, packet fallback candidate
    upload_status: str = "pending"
    attempts: int = 0
    last_error: str | None = None
    # Verification detail, filled by the source-audit stage. The QUOTE and the
    # TIMESTAMP are the evidence — `verified_words` counts words in the quote,
    # never in the model's reply (an earlier version counted the reply, so a
    # summary or a hallucination could pass as a verified transcript).
    verified_words: int | None = None
    verify_quote: str = ""
    verify_timestamp: str = ""
    verify_note: str = ""


class PromptJob(BaseModel):
    prompt_id: str
    prompt_version: str = "v1"
    prompt_hash: str = ""
    status: str = "pending"          # pending | complete | failed
    response_path: str = ""
    citation_path: str = ""
    attempts: int = 0
    last_error: str | None = None


class RunManifest(BaseModel):
    channel_id: str
    notebook_key: str
    # The notebook's URL is its IDENTITY (titles are cosmetic; a failed rename
    # must not make a resumed run create a second notebook).
    notebook_url: str = ""
    state: RunState = RunState.START
    sources: list[SourceEntry] = Field(default_factory=list)
    prompts: list[PromptJob] = Field(default_factory=list)
    history: list[str] = Field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""

    # ── persistence ──────────────────────────────────────────────────────────

    @classmethod
    def path_for(cls, base_dir: Path, channel_id: str, notebook_key: str) -> Path:
        return Path(base_dir) / f"manifest_{channel_id}_{notebook_key}.json"

    @classmethod
    def load_or_create(cls, base_dir: Path, channel_id: str,
                       notebook_key: str) -> "RunManifest":
        p = cls.path_for(base_dir, channel_id, notebook_key)
        if p.exists():
            return cls.model_validate_json(p.read_text(encoding="utf-8"))
        m = cls(channel_id=channel_id, notebook_key=notebook_key,
                created_at=datetime.now(timezone.utc).isoformat())
        m.save(base_dir)
        return m

    def save(self, base_dir: Path) -> None:
        p = self.path_for(Path(base_dir), self.channel_id, self.notebook_key)
        p.parent.mkdir(parents=True, exist_ok=True)
        self.updated_at = datetime.now(timezone.utc).isoformat()
        fd, tmp = tempfile.mkstemp(dir=str(p.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(self.model_dump_json(indent=1))
            os.replace(tmp, p)
        except Exception:
            Path(tmp).unlink(missing_ok=True)
            raise

    # ── state ────────────────────────────────────────────────────────────────

    def transition(self, nxt: RunState, base_dir: Path) -> None:
        """Persist BEFORE the action that follows the new state runs."""
        self.state = advance(self.state, nxt)
        self.history.append(
            f"{datetime.now(timezone.utc).isoformat()} -> {nxt.value}")
        self.save(base_dir)

    def resume_state(self) -> RunState:
        return resume_point(self.state)

    # ── sources (idempotent upload set) ──────────────────────────────────────

    def register_sources(self, packets: list[tuple[str, str, Path]]) -> None:
        """(video_id, role, packet_path) — dedupe by video_id; a changed hash
        marks the entry stale-pending again (re-upload as an updated file)."""
        by_id = {s.video_id: s for s in self.sources}
        for video_id, role, path in packets:
            content_hash = short_hash(Path(path).read_text(encoding="utf-8"))
            prefix = "WIN" if role == "winner" else "CTL"
            remote = f"{prefix}_{video_id}_{content_hash}.md"
            cur = by_id.get(video_id)
            if cur is None:
                self.sources.append(SourceEntry(
                    video_id=video_id, role=role, source_kind="packet",
                    packet_path=str(path),
                    source_hash=content_hash, remote_title=remote))
            elif cur.source_hash != content_hash:
                cur.source_hash = content_hash
                cur.remote_title = remote
                cur.packet_path = str(path)
                cur.upload_status = "pending"   # stale → re-upload; NEVER auto-delete old

    def register_url_sources(self, videos: list[tuple[str, str, str]]) -> None:
        """(video_id, role, url) — URL-first sources (NotebookLM pulls the
        transcript itself). One kind per video: a video already registered as a
        packet stays a packet; a URL entry that later fails import is flipped
        to a packet by the fallback path, never duplicated."""
        by_id = {s.video_id: s for s in self.sources}
        for video_id, role, url in videos:
            if video_id in by_id:
                continue
            self.sources.append(SourceEntry(
                video_id=video_id, role=role, source_kind="youtube_url", url=url))

    def flip_to_packet(self, video_id: str, packet_path: Path) -> None:
        """URL import failed → this video becomes a packet source (ASR/caption
        fallback). The old URL entry is REPLACED in the manifest; removing the
        dead source in the notebook UI stays a manual decision (never
        auto-delete)."""
        for s in self.sources:
            if s.video_id == video_id:
                s.source_kind = "packet"
                s.packet_path = str(packet_path)
                s.source_hash = short_hash(
                    Path(packet_path).read_text(encoding="utf-8"))
                prefix = "WIN" if s.role == "winner" else "CTL"
                s.remote_title = f"{prefix}_{video_id}_{s.source_hash}.md"
                s.upload_status = "pending"
                return

    def pending_uploads(self) -> list[SourceEntry]:
        return [s for s in self.sources if s.upload_status == "pending"]

    # Stages that mean "the UI shows it" vs "we checked it carries evidence".
    UI_OK: ClassVar[set[str]] = {
        "ui_indexed", "indexed", "transcript_verified", "evidence_usable"}
    # ONLY evidence_usable counts. `transcript_verified` was described as
    # "verified but possibly too short to carry evidence" and then included in
    # the evidence pool anyway — the weaker tier meant nothing.
    EVIDENCE_OK: ClassVar[set[str]] = {"evidence_usable"}

    def evidence_sources(self) -> list["SourceEntry"]:
        """Sources a finding may legitimately rest on."""
        return [s for s in self.sources if s.upload_status in self.EVIDENCE_OK]

    def evidence_summary(self) -> dict:
        """What the run may CLAIM, separated from what it merely displayed."""
        counts: dict[str, int] = {}
        for s in self.sources:
            counts[s.upload_status] = counts.get(s.upload_status, 0) + 1
        return {"by_status": counts,
                "ui_listed": sum(1 for s in self.sources
                                 if s.upload_status in self.UI_OK),
                "evidence_usable": len(self.evidence_sources()),
                "total": len(self.sources)}

    def all_indexed(self) -> bool:
        """UI-level completeness only — NOT evidence readiness (see UI_OK)."""
        return bool(self.sources) and all(
            s.upload_status in self.UI_OK for s in self.sources)

    # ── prompts (idempotent job set) ─────────────────────────────────────────

    def register_prompt(self, prompt_id: str, prompt_text: str,
                        version: str = "v1") -> PromptJob:
        h = short_hash(f"{version}|{prompt_text}")
        for j in self.prompts:
            if j.prompt_id == prompt_id:
                if j.prompt_hash != h:      # prompt changed → must re-run
                    j.prompt_hash = h
                    j.prompt_version = version
                    j.status = "pending"
                return j
        job = PromptJob(prompt_id=prompt_id, prompt_version=version, prompt_hash=h)
        self.prompts.append(job)
        return job

    def pending_prompts(self) -> list[PromptJob]:
        return [j for j in self.prompts if j.status != "complete"]
