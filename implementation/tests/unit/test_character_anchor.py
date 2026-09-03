"""Character anchor set (WS1): prompt derivation, caching, resolution order.

Provider is faked — no network, no Flow.
"""

import asyncio
from pathlib import Path

from omnicast.media import character_anchor as ca

DNA = "SAME recurring character Max: round face, red hoodie"


class FakeProvider:
    def __init__(self, fail_after: int | None = None):
        self.calls: list[str] = []
        self.fail_after = fail_after

    async def generate(self, prompt: str, *, output_path: str, **kw) -> str:
        self.calls.append(prompt)
        if self.fail_after is not None and len(self.calls) > self.fail_after:
            raise RuntimeError("provider down")
        Path(output_path).write_bytes(b"png" + bytes([len(self.calls)]))
        return output_path


def test_build_anchor_prompts_contains_dna_and_poses():
    prompts = ca.build_anchor_prompts(DNA, style_prefix="grainy found photo")
    assert len(prompts) == 3
    for p in prompts:
        assert DNA in p and "grainy found photo" in p
    assert "portrait" in prompts[0]
    assert not ca.build_anchor_prompts("")  # no DNA → no anchors


def test_ensure_anchor_generates_and_caches(tmp_path):
    prov = FakeProvider()
    paths = asyncio.run(ca.ensure_anchor_images(
        DNA, prov, anchor_dir=tmp_path, count=3))
    assert len(paths) == 3 and len(prov.calls) == 3
    assert all(Path(p).stat().st_size > 0 for p in paths)

    # Second run: cache hit, provider untouched.
    prov2 = FakeProvider()
    paths2 = asyncio.run(ca.ensure_anchor_images(
        DNA, prov2, anchor_dir=tmp_path, count=3))
    assert paths2 == paths and prov2.calls == []


def test_ensure_anchor_partial_failure_returns_partial(tmp_path):
    prov = FakeProvider(fail_after=1)  # only anchor #1 lands
    paths = asyncio.run(ca.ensure_anchor_images(
        DNA, prov, anchor_dir=tmp_path, count=3))
    assert len(paths) == 1  # never raises, partial kept


def test_ensure_anchor_no_provider_no_dna(tmp_path):
    assert asyncio.run(ca.ensure_anchor_images("", None)) == []
    assert asyncio.run(ca.ensure_anchor_images(
        DNA, None, anchor_dir=tmp_path)) == []  # nothing cached, no provider


def test_resolve_reference_images_precedence(tmp_path, monkeypatch):
    # portrait first, explicit refs kept, missing files dropped.
    portrait = tmp_path / "portrait.png"
    portrait.write_bytes(b"png1")
    ref = tmp_path / "ref.png"
    ref.write_bytes(b"png2")
    channel = {
        "character_portrait": str(portrait),
        "reference_images": [str(ref), str(tmp_path / "missing.png")],
    }
    out = ca.resolve_reference_images(channel, "")
    assert out[0] == str(portrait.resolve())
    assert str(ref.resolve()) in out and len(out) == 2


def test_resolve_reference_images_empty_channel():
    assert ca.resolve_reference_images(None, "") == []
    assert ca.resolve_reference_images({}, "") == []
