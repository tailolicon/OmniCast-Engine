"""CapCut draft bridge: subtitles in, generated speech out.

These run against synthetic drafts shaped like the real thing (text material
whose `content` is itself a JSON document, microsecond timeranges) so the
writer can be exercised without a CapCut install.
"""

from __future__ import annotations

import json

import pytest

from omnicast.reup.capcut.draft import (
    MS_TO_US,
    CapCutDraftError,
    SubtitleLine,
    list_drafts,
    read_generated_audio,
    write_draft,
)


def _template(tmp_path, name="template"):
    """A minimal draft with one text layer, mirroring CapCut's shape."""
    draft = tmp_path / name
    draft.mkdir()
    content = {
        "id": "OLD-ID",
        "duration": 5_000_000,
        "canvas_config": {"width": 1920, "height": 1080},
        "materials": {
            "texts": [
                {
                    "id": "TEXT-MAT-1",
                    "base_content": "cũ",
                    "content": json.dumps(
                        {
                            "text": "cũ",
                            "styles": [{"range": [0, 2], "font": {"path": "C:/f.ttf"}}],
                        },
                        ensure_ascii=False,
                    ),
                }
            ],
            "audios": [],
        },
        "tracks": [
            {
                "type": "text",
                "segments": [
                    {
                        "id": "SEG-1",
                        "material_id": "TEXT-MAT-1",
                        "target_timerange": {"start": 0, "duration": 1_000_000},
                    }
                ],
            }
        ],
    }
    (draft / "draft_content.json").write_text(
        json.dumps(content, ensure_ascii=False), encoding="utf-8"
    )
    (draft / ".locked").write_text("", encoding="utf-8")
    return draft


def _lines():
    return [
        SubtitleLine(0, 0, 2_000, "Anh còn nhớ tôi là ai không?"),
        SubtitleLine(1, 2_000, 3_500, "Tôi xin anh đấy."),
    ]


def test_writes_one_material_and_segment_per_line(tmp_path):
    result = write_draft(
        _lines(), template_draft=_template(tmp_path), name="out", root=tmp_path
    )
    doc = json.loads((result.draft_dir / "draft_content.json").read_text(encoding="utf-8"))
    assert len(doc["materials"]["texts"]) == 2
    assert len(doc["tracks"][0]["segments"]) == 2
    assert result.line_count == 2


def test_text_is_written_into_the_nested_content_document(tmp_path):
    result = write_draft(
        _lines(), template_draft=_template(tmp_path), name="out", root=tmp_path
    )
    doc = json.loads((result.draft_dir / "draft_content.json").read_text(encoding="utf-8"))
    first = json.loads(doc["materials"]["texts"][0]["content"])
    assert first["text"] == "Anh còn nhớ tôi là ai không?"
    # The font path came from the template and must survive.
    assert first["styles"][0]["font"]["path"] == "C:/f.ttf"


def test_style_ranges_are_resized_to_the_new_text(tmp_path):
    # A stale range past the end of a shorter line makes CapCut drop styling.
    result = write_draft(
        [SubtitleLine(0, 0, 500, "a")],
        template_draft=_template(tmp_path),
        name="out",
        root=tmp_path,
    )
    doc = json.loads((result.draft_dir / "draft_content.json").read_text(encoding="utf-8"))
    assert json.loads(doc["materials"]["texts"][0]["content"])["styles"][0]["range"] == [0, 1]


def test_timeranges_are_microseconds(tmp_path):
    result = write_draft(
        _lines(), template_draft=_template(tmp_path), name="out", root=tmp_path
    )
    doc = json.loads((result.draft_dir / "draft_content.json").read_text(encoding="utf-8"))
    second = doc["tracks"][0]["segments"][1]["target_timerange"]
    assert second["start"] == 2_000 * MS_TO_US
    assert second["duration"] == 1_500 * MS_TO_US


def test_material_ids_are_unique_and_referenced_by_their_segment(tmp_path):
    result = write_draft(
        _lines(), template_draft=_template(tmp_path), name="out", root=tmp_path
    )
    doc = json.loads((result.draft_dir / "draft_content.json").read_text(encoding="utf-8"))
    ids = [m["id"] for m in doc["materials"]["texts"]]
    assert len(set(ids)) == 2, "duplicate ids make CapCut render one line twice"
    assert [s["material_id"] for s in doc["tracks"][0]["segments"]] == ids


def test_lines_are_ordered_by_time(tmp_path):
    out_of_order = [
        SubtitleLine(1, 5_000, 6_000, "sau"),
        SubtitleLine(0, 0, 1_000, "trước"),
    ]
    result = write_draft(
        out_of_order, template_draft=_template(tmp_path), name="out", root=tmp_path
    )
    doc = json.loads((result.draft_dir / "draft_content.json").read_text(encoding="utf-8"))
    starts = [s["target_timerange"]["start"] for s in doc["tracks"][0]["segments"]]
    assert starts == sorted(starts)


def test_lock_file_is_not_copied(tmp_path):
    # Copying `.locked` makes CapCut think the project is open elsewhere.
    result = write_draft(
        _lines(), template_draft=_template(tmp_path), name="out", root=tmp_path
    )
    assert not (result.draft_dir / ".locked").exists()


def test_empty_lines_are_skipped(tmp_path):
    lines = [SubtitleLine(0, 0, 500, "  "), SubtitleLine(1, 500, 1_000, "thật")]
    result = write_draft(lines, template_draft=_template(tmp_path), name="out", root=tmp_path)
    assert result.line_count == 1


def test_all_empty_is_an_error(tmp_path):
    with pytest.raises(CapCutDraftError, match="empty"):
        write_draft(
            [SubtitleLine(0, 0, 500, "")],
            template_draft=_template(tmp_path),
            name="out",
            root=tmp_path,
        )


def test_refuses_to_overwrite_an_existing_draft(tmp_path):
    template = _template(tmp_path)
    write_draft(_lines(), template_draft=template, name="out", root=tmp_path)
    with pytest.raises(CapCutDraftError, match="already exists"):
        write_draft(_lines(), template_draft=template, name="out", root=tmp_path)


def test_template_without_a_text_layer_is_rejected(tmp_path):
    bare = tmp_path / "bare"
    bare.mkdir()
    (bare / "draft_content.json").write_text(
        json.dumps({"materials": {"texts": []}, "tracks": []}), encoding="utf-8"
    )
    with pytest.raises(CapCutDraftError, match="text layer"):
        write_draft(_lines(), template_draft=bare, name="out", root=tmp_path)


def test_reading_a_draft_with_no_audio_yet_is_not_an_error(tmp_path):
    result = write_draft(
        _lines(), template_draft=_template(tmp_path), name="out", root=tmp_path
    )
    assert read_generated_audio(result.draft_dir).is_empty


def test_generated_audio_is_matched_to_lines_by_start_time(tmp_path):
    result = write_draft(
        _lines(), template_draft=_template(tmp_path), name="out", root=tmp_path
    )
    wav = tmp_path / "voice.wav"
    wav.write_bytes(b"RIFF")

    doc = json.loads((result.draft_dir / "draft_content.json").read_text(encoding="utf-8"))
    doc["materials"]["audios"] = [{"id": "A1", "path": str(wav)}]
    doc["tracks"].append(
        {
            "type": "audio",
            "segments": [
                {
                    "material_id": "A1",
                    # Same start as the SECOND text line.
                    "target_timerange": {"start": 2_000 * MS_TO_US, "duration": 900_000},
                }
            ],
        }
    )
    (result.draft_dir / "draft_content.json").write_text(
        json.dumps(doc, ensure_ascii=False), encoding="utf-8"
    )

    read = read_generated_audio(result.draft_dir)
    assert [c.segment_index for c in read.clips] == [1]
    assert read.clips[0].duration_ms == 900


def test_audio_whose_file_is_gone_is_reported_not_returned(tmp_path):
    result = write_draft(
        _lines(), template_draft=_template(tmp_path), name="out", root=tmp_path
    )
    doc = json.loads((result.draft_dir / "draft_content.json").read_text(encoding="utf-8"))
    doc["materials"]["audios"] = [{"id": "A1", "path": str(tmp_path / "missing.wav")}]
    doc["tracks"].append(
        {
            "type": "audio",
            "segments": [{"material_id": "A1", "target_timerange": {"start": 0, "duration": 1}}],
        }
    )
    (result.draft_dir / "draft_content.json").write_text(
        json.dumps(doc, ensure_ascii=False), encoding="utf-8"
    )

    read = read_generated_audio(result.draft_dir)
    assert read.is_empty
    assert read.unmatched, "a vanished file must surface, not disappear silently"


def test_listing_drafts_skips_folders_without_content(tmp_path):
    _template(tmp_path, "real")
    (tmp_path / "not-a-draft").mkdir()
    assert [d.name for d in list_drafts(tmp_path)] == ["real"]
