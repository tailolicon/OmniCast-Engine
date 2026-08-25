from omnicast.media.output_audit import OutputQualityAuditor
import json


def _write_mp4_placeholder(path):
    path.write_bytes(b"0" * 700_000)


def _patch_publishable_probe(auditor):
    auditor._ffprobe = lambda _: {
        "format": {"duration": "600", "bit_rate": "4200000"},
        "streams": [
            {"codec_type": "video", "codec_name": "h264", "duration": "600", "width": 1920, "height": 1080},
            {"codec_type": "audio", "codec_name": "aac", "sample_rate": "48000", "channels": 2, "bit_rate": "192000"},
        ],
    }


def test_output_audit_passes_publishable_audio(tmp_path):
    output = tmp_path / "final.mp4"
    _write_mp4_placeholder(output)
    auditor = OutputQualityAuditor(measure_loudness=False)
    _patch_publishable_probe(auditor)

    result = auditor.inspect(output)

    assert result["passed"] is True
    assert result["issues"] == []


def test_output_audit_rejects_non_mastered_audio(tmp_path):
    output = tmp_path / "final.mp4"
    _write_mp4_placeholder(output)
    auditor = OutputQualityAuditor(measure_loudness=False)
    auditor._ffprobe = lambda _: {
        "format": {"duration": "300", "bit_rate": "1800000"},
        "streams": [
            {"codec_type": "video", "codec_name": "h264", "duration": "300", "width": 1280, "height": 720},
            {"codec_type": "audio", "codec_name": "mp3", "sample_rate": "44100", "channels": 1, "bit_rate": "128000"},
        ],
    }

    result = auditor.inspect(output)

    assert result["passed"] is False
    assert "duration_too_short" in result["issues"]
    assert "unexpected_audio_codec" in result["issues"]
    assert "audio_sample_rate_not_48000" in result["issues"]
    assert "audio_not_stereo" in result["issues"]
    assert "audio_bitrate_below_192k" in result["issues"]


def test_output_audit_rejects_loudness_out_of_range(tmp_path):
    output = tmp_path / "final.mp4"
    _write_mp4_placeholder(output)
    auditor = OutputQualityAuditor()
    auditor._ffprobe = lambda _: {
        "format": {"duration": "600", "bit_rate": "4200000"},
        "streams": [
            {"codec_type": "video", "codec_name": "h264", "duration": "600", "width": 1920, "height": 1080},
            {"codec_type": "audio", "codec_name": "aac", "sample_rate": "48000", "channels": 2, "bit_rate": "192000"},
        ],
    }
    auditor._measure_integrated_lufs = lambda _: -20.0

    result = auditor.inspect(output)

    assert result["passed"] is False
    assert "audio_loudness_out_of_range" in result["issues"]


def test_product_audit_passes_relevant_visual_prompts_and_writes_sidecar(tmp_path):
    product = tmp_path / "product"
    (product / "variants").mkdir(parents=True)
    output = product / "video.mp4"
    _write_mp4_placeholder(output)
    (product / "meta.json").write_text(
        json.dumps({"topic": "Beat GLP-1 Nausea Naturally", "niche": "health"}),
        encoding="utf-8",
    )
    (product / "script.txt").write_text(
        "Medical disclaimer. GLP-1 nausea relief needs hydration, ginger tea, and doctor guidance.",
        encoding="utf-8",
    )
    (product / "variants" / "variant_A_score90.json").write_text(
        json.dumps({
            "scenes": [
                {
                    "voiceover": "Hydration and ginger tea may ease GLP-1 nausea.",
                    "visual_prompt": "Doctor speaking with patient about GLP-1 nausea, ginger tea, and hydration",
                }
            ]
        }),
        encoding="utf-8",
    )
    auditor = OutputQualityAuditor(measure_loudness=False)
    _patch_publishable_probe(auditor)

    result = auditor.inspect_product(output, product)

    assert result["passed"] is True
    assert result["issues"] == []
    sidecar = product / "_output_audit.json"
    assert sidecar.exists()
    saved = json.loads(sidecar.read_text(encoding="utf-8"))
    assert saved["visual_relevance"]["passed"] is True


def test_product_audit_rejects_editor_ui_visual_for_health_topic(tmp_path):
    product = tmp_path / "product"
    (product / "variants").mkdir(parents=True)
    output = product / "video.mp4"
    _write_mp4_placeholder(output)
    (product / "meta.json").write_text(
        json.dumps({"topic": "Beat GLP-1 Nausea Naturally", "niche": "health"}),
        encoding="utf-8",
    )
    (product / "script.txt").write_text(
        "Medical disclaimer. GLP-1 nausea relief with hydration and doctor guidance.",
        encoding="utf-8",
    )
    (product / "variants" / "variant_A_score90.json").write_text(
        json.dumps({
            "scenes": [
                {
                    "voiceover": "Nausea can feel overwhelming.",
                    "visual_prompt": "Adobe Premiere Pro video editing timeline with color grading interface",
                }
            ]
        }),
        encoding="utf-8",
    )
    auditor = OutputQualityAuditor(measure_loudness=False)
    _patch_publishable_probe(auditor)

    result = auditor.inspect_product(output, product)

    assert result["passed"] is False
    assert "visual_relevance:editor_ui_visual_detected" in result["issues"]


def test_final_board_is_the_storyboard_source_of_truth(tmp_path):
    """The renderer writes board_final.json; auditing only draft storyboard
    names means the quality gate can judge a board that was never rendered."""
    product = tmp_path / "product"
    product.mkdir()
    scenes = [
        {
            "voiceover": f"Social Security rule scene {i}",
            "visual_type": "stock_video" if i < 4 else "chart_render",
            "stock_query": "social security statement" if i < 2 else f"retirement desk {i}",
            "visual_prompt": f"Social Security statement detail {i}",
        }
        for i in range(6)
    ]
    (product / "board_final.json").write_text(
        json.dumps(scenes), encoding="utf-8")

    auditor = OutputQualityAuditor(measure_loudness=False)
    summary = auditor._storyboard_summary(product)
    evidence = auditor._storyboard_evidence(product, {})
    visual_texts = auditor._collect_product_visual_texts(product)

    assert summary["scenes"] == 6
    assert summary["visual_source_mix"] == {
        "chart_render": 0.333, "stock_video": 0.667}
    assert evidence["repeated_shot_ratio"] > 0
    assert any("Social Security statement" in item for item in visual_texts)


def test_required_visual_match_qc_is_bound_to_the_exact_render(tmp_path):
    product = tmp_path / "product"
    product.mkdir()
    video = product / "video.mp4"
    video.write_bytes(b"current rendered cut")
    auditor = OutputQualityAuditor(measure_loudness=False)

    missing = auditor.inspect_visual_match(product, video, required=True)
    assert missing["passed"] is False
    assert "visual_match_qc_missing" in missing["issues"]

    (product / "_visual_match_qc.json").write_text(json.dumps({
        "video_sha256": "stale",
        "shots_scored": 20,
        "avg_score": 9,
        "below_threshold": 0,
        "errors": 0,
    }), encoding="utf-8")
    stale = auditor.inspect_visual_match(product, video, required=True)
    assert stale["passed"] is False
    assert "visual_match_qc_stale_render" in stale["issues"]

    (product / "_visual_match_qc.json").write_text(json.dumps({
        "video_sha256": auditor.artifact_hash(video),
        "shots_scored": 20,
        "avg_score": 7.2,
        "below_threshold": 2,
        "errors": 0,
    }), encoding="utf-8")
    current = auditor.inspect_visual_match(product, video, required=True)
    assert current["passed"] is True
    assert current["coverage_ratio"] == 1.0
