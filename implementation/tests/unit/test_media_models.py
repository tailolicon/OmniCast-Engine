import pytest
from pydantic import ValidationError
from omnicast.media.models import (
    TTSEngine, ImageGenBackend, VideoGenBackend, MusicSource, MediaStatus,
    TTSRequest, TTSResult, ImageGenRequest, ImageGenResult,
    VideoGenRequest, VideoGenResult, MusicRequest, MusicResult,
    SubtitleRequest, SubtitleResult, ThumbnailRequest, ThumbnailResult,
    RenderLayer, RenderJob, RenderResult,
    ContentFingerprint, MediaPipelineState,
)


class TestEnums:
    def test_tts_engine_values(self):
        assert TTSEngine.KOKORO == "kokoro"
        assert TTSEngine.XTTSV2 == "xttsv2"
        assert TTSEngine.EDGE == "edge"
        assert TTSEngine.F5TTS == "f5tts"

    def test_media_status_values(self):
        assert MediaStatus.PENDING == "pending"
        assert MediaStatus.DONE == "done"
        assert MediaStatus.FAILED == "failed"

    def test_music_source_values(self):
        assert MusicSource.YT_AUDIO_LIB == "yt_audio_lib"
        assert MusicSource.ACE_STEP == "ace_step"


class TestTTSModels:
    def test_request_defaults(self):
        r = TTSRequest(text="Hello world")
        assert r.voice_profile == "kokoro:af_heart"
        assert r.engine == TTSEngine.KOKORO
        assert r.target_lufs == -14.0
        assert r.voice_clone is None

    def test_request_with_clone(self):
        r = TTSRequest(text="Hi", voice_clone="clone_v1", engine=TTSEngine.XTTSV2)
        assert r.voice_clone == "clone_v1"

    def test_result_defaults(self):
        r = TTSResult()
        assert r.status == MediaStatus.DONE
        assert r.sample_rate == 24000

    def test_frozen(self):
        r = TTSRequest(text="X")
        with pytest.raises(ValidationError):
            r.text = "Y"


class TestImageGenModels:
    def test_request_defaults(self):
        r = ImageGenRequest(prompt="A cat")
        assert r.backend == ImageGenBackend.SDXL
        assert r.width == 1920 and r.height == 1080
        assert r.ip_adapter_weight == 0.6

    def test_ip_adapter_bounds(self):
        ImageGenRequest(prompt="X", ip_adapter_weight=0.0)
        ImageGenRequest(prompt="X", ip_adapter_weight=1.0)
        with pytest.raises(ValidationError):
            ImageGenRequest(prompt="X", ip_adapter_weight=1.1)
        with pytest.raises(ValidationError):
            ImageGenRequest(prompt="X", ip_adapter_weight=-0.1)


class TestVideoGenModels:
    def test_request_defaults(self):
        r = VideoGenRequest(prompt="Ocean waves")
        assert r.backend == VideoGenBackend.WAN21
        assert r.duration_seconds == 5.0

    def test_duration_bounds(self):
        VideoGenRequest(prompt="X", duration_seconds=1.0)
        VideoGenRequest(prompt="X", duration_seconds=10.0)
        with pytest.raises(ValidationError):
            VideoGenRequest(prompt="X", duration_seconds=0.5)
        with pytest.raises(ValidationError):
            VideoGenRequest(prompt="X", duration_seconds=11.0)


class TestMusicModels:
    def test_request_defaults(self):
        r = MusicRequest()
        assert r.mood == "cinematic"
        assert r.bpm_range == (120, 140)
        assert len(r.source_priority) == 3
        assert r.source_priority[0] == MusicSource.YT_AUDIO_LIB

    def test_result_with_attribution(self):
        r = MusicResult(attribution="Track by Artist - CC BY 4.0", source_used=MusicSource.ROYALTY_FREE)
        assert r.attribution != ""


class TestSubtitleModels:
    def test_request(self):
        r = SubtitleRequest(audio_path="/tmp/audio.wav")
        assert r.language == "en"

    def test_result(self):
        r = SubtitleResult(srt_path="/tmp/sub.srt", word_count=150, duration_seconds=60.0)
        assert r.word_count == 150


class TestThumbnailModels:
    def test_request_defaults(self):
        r = ThumbnailRequest(title="Top 10 Tips")
        assert r.style == "dark_contrast"
        assert r.variants == 3
        assert len(r.color_palette) == 3

    def test_variants_bounds(self):
        ThumbnailRequest(title="X", variants=1)
        ThumbnailRequest(title="X", variants=5)
        with pytest.raises(ValidationError):
            ThumbnailRequest(title="X", variants=0)
        with pytest.raises(ValidationError):
            ThumbnailRequest(title="X", variants=6)


class TestRenderModels:
    def test_render_layer(self):
        l = RenderLayer(layer_type="music", file_path="/tmp/bg.wav", volume_db=-20.0)
        assert l.volume_db == -20.0

    def test_render_job_defaults(self):
        j = RenderJob(job_id="j1", channel_id="ch1")
        assert j.resolution == "1920x1080"
        assert j.codec == "h264"
        assert j.crossfade_seconds == 0.5
        assert j.music_duck_db == -20.0

    def test_render_result(self):
        r = RenderResult(output_path="/tmp/final.mp4", duration_seconds=300.0, file_size_mb=150.5)
        assert r.file_size_mb == 150.5


class TestContentFingerprint:
    def test_identical_score(self):
        fp = ContentFingerprint(
            video_id="v1", script_hash="abc", visual_hashes=["h1", "h2"],
            audio_fingerprint="af1", music_fingerprint="mf1", structure_signature="s1"
        )
        assert fp.similarity_score(fp) == 1.0

    def test_empty_score(self):
        fp1 = ContentFingerprint(video_id="v1")
        fp2 = ContentFingerprint(video_id="v2")
        assert fp1.similarity_score(fp2) == 0.0

    def test_partial_match(self):
        fp1 = ContentFingerprint(video_id="v1", script_hash="abc", audio_fingerprint="af1")
        fp2 = ContentFingerprint(video_id="v2", script_hash="abc", audio_fingerprint="af2")
        score = fp1.similarity_score(fp2)
        assert 0.0 < score < 1.0

    def test_visual_hash_overlap(self):
        fp1 = ContentFingerprint(video_id="v1", visual_hashes=["h1", "h2", "h3"])
        fp2 = ContentFingerprint(video_id="v2", visual_hashes=["h2", "h3", "h4"])
        score = fp1.similarity_score(fp2)
        assert score > 0.0

    def test_threshold_check(self):
        fp1 = ContentFingerprint(
            video_id="v1", script_hash="x", visual_hashes=["h1"],
            audio_fingerprint="a", music_fingerprint="m", structure_signature="s"
        )
        fp2 = ContentFingerprint(
            video_id="v2", script_hash="x", visual_hashes=["h1"],
            audio_fingerprint="a", music_fingerprint="m", structure_signature="s"
        )
        assert fp2.similarity_score(fp1) > 0.7


class TestMediaPipelineState:
    def test_initial_state(self):
        s = MediaPipelineState(video_id="v1", channel_id="ch1")
        assert not s.all_done
        assert not s.has_failure

    def test_all_done(self):
        s = MediaPipelineState(
            video_id="v1", channel_id="ch1",
            tts=MediaStatus.DONE, images=MediaStatus.DONE,
            video_gen=MediaStatus.SKIPPED, music=MediaStatus.DONE,
            subtitle=MediaStatus.DONE, thumbnail=MediaStatus.DONE,
            render=MediaStatus.DONE, fingerprint=MediaStatus.DONE,
        )
        assert s.all_done
        assert not s.has_failure

    def test_has_failure(self):
        s = MediaPipelineState(
            video_id="v1", channel_id="ch1",
            tts=MediaStatus.DONE, images=MediaStatus.FAILED,
        )
        assert s.has_failure
        assert not s.all_done

    def test_mixed_done_skipped(self):
        s = MediaPipelineState(
            video_id="v1", channel_id="ch1",
            tts=MediaStatus.DONE, images=MediaStatus.DONE,
            video_gen=MediaStatus.SKIPPED, music=MediaStatus.DONE,
            subtitle=MediaStatus.DONE, thumbnail=MediaStatus.DONE,
            render=MediaStatus.DONE, fingerprint=MediaStatus.SKIPPED,
        )
        assert s.all_done

    def test_frozen(self):
        s = MediaPipelineState(video_id="v1", channel_id="ch1")
        with pytest.raises(ValidationError):
            s.video_id = "v2"
