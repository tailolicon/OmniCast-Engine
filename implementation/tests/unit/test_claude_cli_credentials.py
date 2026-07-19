"""OAuth refresh rotates the refresh token INSIDE the isolated per-PID config
dir; if it is not synced back to ~/.claude the machine silently loses auth at
interpreter exit (observed 2026-07-16). These tests pin the two-way sync."""

from __future__ import annotations

import os
import time
from pathlib import Path

import omnicast.llm.claude_cli as cli


def _write(path: Path, payload: str, mtime: float | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")
    if mtime is not None:
        os.utime(path, (mtime, mtime))


def test_refreshed_iso_token_is_copied_back_to_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    iso = tmp_path / "iso"
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    monkeypatch.setattr(cli, "_ISO_DIR", iso)
    now = time.time()
    _write(home / ".claude" / ".credentials.json", '{"token":"stale"}', now - 600)
    _write(iso / ".credentials.json", '{"token":"rotated"}', now)

    cli._sync_credentials_back()

    assert (home / ".claude" / ".credentials.json").read_text(
        encoding="utf-8") == '{"token":"rotated"}'


def test_older_iso_copy_never_clobbers_a_newer_home_login(tmp_path, monkeypatch):
    home = tmp_path / "home"
    iso = tmp_path / "iso"
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    monkeypatch.setattr(cli, "_ISO_DIR", iso)
    now = time.time()
    # The operator re-ran `claude /login` AFTER this process copied its snapshot.
    _write(iso / ".credentials.json", '{"token":"snapshot"}', now - 600)
    _write(home / ".claude" / ".credentials.json", '{"token":"fresh-login"}', now)

    cli._sync_credentials_back()

    assert (home / ".claude" / ".credentials.json").read_text(
        encoding="utf-8") == '{"token":"fresh-login"}'


def test_sync_back_is_a_noop_without_an_iso_credentials_file(tmp_path, monkeypatch):
    home = tmp_path / "home"
    iso = tmp_path / "iso"
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    monkeypatch.setattr(cli, "_ISO_DIR", iso)
    _write(home / ".claude" / ".credentials.json", '{"token":"only"}')

    cli._sync_credentials_back()

    assert (home / ".claude" / ".credentials.json").read_text(
        encoding="utf-8") == '{"token":"only"}'
