"""Full transcript + ASR fallback (strategic review P0 item 3).

The bug being pinned: `_fetch_transcript` returned `" ".join(parts)[:3500]`, so
every claim the script playbook made about structure, pacing, retention and CTA
placement came from roughly the first four minutes — and nothing in the output
said so. These tests hold the line on "no silent truncation" and on the ASR
fallback that stops caption-less channels from vanishing from the sample."""

from __future__ import annotations

from omnicast.analytics import transcript as tr


def _seg(start, text, duration=3.0):
    return tr.Segment(start=start, text=text, duration=duration)


def _t(segments, **kw):
    return tr.Transcript(
        video_id=kw.pop("video_id", "v1"),
        text=" ".join(s.text for s in segments),
        source=kw.pop("source", "captions"),
        segments=tuple(segments),
        **kw,
    )


def test_chunks_cover_the_whole_transcript_not_just_the_opening():
    """The regression itself: a 20k-character transcript must reach the model in
    full, not as its first 3,500 characters."""
    body = " ".join(f"word{i}" for i in range(4000))
    t = tr.Transcript(video_id="v", text=body, source="captions")
    chunks = t.chunks(max_chars=5000, overlap=200)
    assert len(chunks) > 1
    # The tail of the video is present somewhere — previously it never was.
    assert "word3999" in chunks[-1]
    # And so is the opening.
    assert "word0" in chunks[0]


def test_short_transcript_is_a_single_chunk():
    t = tr.Transcript(video_id="v", text="short enough", source="captions")
    assert t.chunks(max_chars=5000) == ["short enough"]


def test_head_chars_reports_that_it_truncated():
    """Bounding context is allowed; hiding it is not."""
    t = tr.Transcript(video_id="v", text="x" * 100, source="captions")
    text, truncated = t.head_chars(40)
    assert len(text) == 40
    assert truncated is True
    text, truncated = t.head_chars(500)
    assert truncated is False


def test_window_reads_a_real_time_range_not_a_character_count():
    """The first 30 SECONDS is a different thing from the first N characters —
    the hook analyser needs the former."""
    t = _t([
        _seg(0.0, "Here is the promise"),
        _seg(5.0, "and the setup"),
        _seg(40.0, "much later content"),
    ])
    hook = t.window(0, 30)
    assert "promise" in hook and "setup" in hook
    assert "later" not in hook


def test_covered_seconds_exposes_a_partial_transcript():
    t = _t([_seg(0.0, "a"), _seg(100.0, "b", duration=5.0)])
    assert t.covered_seconds == 105.0


def test_failed_fetch_says_why_instead_of_returning_empty_string():
    """`return ""` made 'captions disabled' indistinguishable from 'video with
    nothing to say'. Sample thinness has to be visible."""
    t = tr._empty("v9", "captions unavailable: TranscriptsDisabled")
    assert t.ok is False
    assert "TranscriptsDisabled" in t.note
    assert "no transcript" in t.describe()


def test_asr_declines_over_long_videos_and_records_the_reason(monkeypatch):
    called = {"downloaded": False}

    def _never(*a, **k):
        called["downloaded"] = True
        return ""

    monkeypatch.setattr(tr, "_download_audio", _never)
    out = tr.transcribe_with_asr("v", duration_minutes=180.0, max_minutes=45.0)
    assert out.ok is False
    assert "exceeds" in out.note
    assert called["downloaded"] is False  # no three-hour download attempted


def test_fetch_transcript_falls_back_to_asr_when_captions_are_missing(monkeypatch):
    """Channels that disable captions are not a random subset — they skew small
    and non-English-first, exactly the population the cohort work is trying to
    stop under-sampling."""
    monkeypatch.setattr(tr, "fetch_captions", lambda vid, languages=(): tr._empty(vid, "no captions"))
    monkeypatch.setattr(
        tr, "transcribe_with_asr",
        lambda vid, **kw: tr.Transcript(video_id=vid, text="spoken words", source="asr"),
    )
    out = tr.fetch_transcript("v1")
    assert out.source == "asr"
    assert out.ok


def test_captions_win_over_asr_when_available(monkeypatch):
    monkeypatch.setattr(
        tr, "fetch_captions",
        lambda vid, languages=(): tr.Transcript(video_id=vid, text="captioned", source="captions"),
    )
    monkeypatch.setattr(tr, "transcribe_with_asr", lambda vid, **kw: (_ for _ in ()).throw(AssertionError))
    assert tr.fetch_transcript("v1").source == "captions"


def test_asr_can_be_disabled_and_the_reason_survives(monkeypatch):
    monkeypatch.setattr(tr, "fetch_captions", lambda vid, languages=(): tr._empty(vid, "captions unavailable"))
    out = tr.fetch_transcript("v1", allow_asr=False)
    assert out.ok is False
    assert "captions unavailable" in out.note
