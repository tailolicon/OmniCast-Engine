"""Flow Ingredients plumbing (WS1): ref-image filtering, env resolution,
attach behavior against a stubbed page. No browser, no network."""

import os
from pathlib import Path

import pytest

pytest.importorskip("google.genai")  # flow_browser imports image_gemini
from omnicast.media.providers.flow_browser import FlowProvider, _FlowSession


def _mk(tmp_path, name) -> str:
    p = tmp_path / name
    p.write_bytes(b"png")
    return str(p)


# ── _existing_refs / set_ref_images ──────────────────────────────────────────

def test_existing_refs_filters_and_caps(tmp_path):
    good = [_mk(tmp_path, f"a{i}.png") for i in range(5)]
    empty = tmp_path / "empty.png"
    empty.write_bytes(b"")
    refs = _FlowSession._existing_refs(
        good + [str(empty), str(tmp_path / "missing.png")])
    # missing + empty dropped, capped at MAX_INGREDIENTS
    assert len(refs) == _FlowSession.MAX_INGREDIENTS
    assert all(Path(r).exists() for r in refs)


def test_set_ref_images_resets_attached_flag(tmp_path):
    s = _FlowSession.__new__(_FlowSession)  # no browser launch
    s._ref_images = []
    s._ingredients_attached = True
    s.set_ref_images([_mk(tmp_path, "x.png")])
    assert s._ref_images and s._ingredients_attached is False
    # same set again → no reset churn
    s._ingredients_attached = True
    s.set_ref_images(s._ref_images)
    assert s._ingredients_attached is True


# ── attach against a stubbed page ────────────────────────────────────────────

class _StubLocator:
    def __init__(self, n, page):
        self._n = n
        self._page = page

    def count(self):
        return self._n

    @property
    def first(self):
        return self

    def click(self, timeout=None):
        pass

    def set_input_files(self, files):
        self._page.uploaded = list(files)


class _StubKeyboard:
    def press(self, key):
        pass


class _StubPage:
    """Page whose composer has a file input."""
    def __init__(self, has_file_input=True):
        self.has_file_input = has_file_input
        self.uploaded = None
        self.keyboard = _StubKeyboard()

    def locator(self, sel):
        if sel == 'input[type="file"]':
            return _StubLocator(1 if self.has_file_input else 0, self)
        return _StubLocator(0, self)

    def wait_for_timeout(self, ms):
        pass


def _bare_session(refs) -> _FlowSession:
    s = _FlowSession.__new__(_FlowSession)
    s._ref_images = refs
    s._ingredients_attached = False
    return s


def test_attach_ingredients_uploads_refs(tmp_path):
    refs = [_mk(tmp_path, "anchor.png")]
    s = _bare_session(refs)
    page = _StubPage()
    assert s._attach_ingredients(page) is True
    assert page.uploaded == refs
    assert s._ingredients_attached is True


def test_attach_ingredients_no_input_is_graceful(tmp_path):
    s = _bare_session([_mk(tmp_path, "anchor.png")])
    page = _StubPage(has_file_input=False)
    assert s._attach_ingredients(page) is False  # logged, never raises
    assert s._ingredients_attached is False


# ── FlowProvider env plumbing ────────────────────────────────────────────────

def test_provider_reads_flow_ingredients_env(tmp_path, monkeypatch):
    a, b = _mk(tmp_path, "a.png"), _mk(tmp_path, "b.png")
    monkeypatch.setenv("FLOW_INGREDIENTS", os.pathsep.join([a, b]))
    prov = FlowProvider(profile_dir=str(tmp_path), project_url="http://x")
    assert prov._reference_images == [a, b]


def test_provider_env_empty_means_no_refs(tmp_path, monkeypatch):
    monkeypatch.delenv("FLOW_INGREDIENTS", raising=False)
    prov = FlowProvider(profile_dir=str(tmp_path), project_url="http://x")
    assert prov._reference_images == []


def test_set_reference_images_updates_live_session(tmp_path):
    prov = FlowProvider(profile_dir=str(tmp_path), project_url="http://x")
    s = _bare_session([])
    prov._session = s
    ref = _mk(tmp_path, "r.png")
    prov.set_reference_images([ref])
    assert s._ref_images == [str(Path(ref).resolve())]
