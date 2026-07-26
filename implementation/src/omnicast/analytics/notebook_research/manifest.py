"""Idempotent run manifest for the NotebookLM browser worker.

One JSON file per (channel, notebook_key) run, written atomically after every
state change / source upload / prompt completion, so a killed process resumes
without re-uploading sources or re-running finished prompts. This is the
memory of the state machine; the browser holds no state of its own.
"""

from __future__ import annotations

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
    packet_path: str = ""
    source_hash: str = ""            # short hash of packet content
    remote_title: str = ""           # filename as it appears in the source list
    upload_status: str = "pending"   # pending | uploaded | indexed | failed
    attempts: int = 0
    last_error: str | None = None


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
                    video_id=video_id, role=role, packet_path=str(path),
                    source_hash=content_hash, remote_title=remote))
            elif cur.source_hash != content_hash:
                cur.source_hash = content_hash
                cur.remote_title = remote
                cur.packet_path = str(path)
                cur.upload_status = "pending"   # stale → re-upload; NEVER auto-delete old

    def pending_uploads(self) -> list[SourceEntry]:
        return [s for s in self.sources if s.upload_status == "pending"]

    def all_indexed(self) -> bool:
        return bool(self.sources) and all(
            s.upload_status == "indexed" for s in self.sources)

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
