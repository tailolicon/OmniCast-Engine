import pytest
from omnicast.media.fingerprint import FingerprintModule
from omnicast.media.models import ContentFingerprint


@pytest.fixture
def fp():
    return FingerprintModule()


class TestScriptFingerprint:
    def test_deterministic(self, fp):
        h1 = fp.fingerprint_script("Hello World")
        h2 = fp.fingerprint_script("Hello World")
        assert h1 == h2

    def test_case_insensitive(self, fp):
        h1 = fp.fingerprint_script("Hello World")
        h2 = fp.fingerprint_script("hello world")
        assert h1 == h2

    def test_whitespace_normalized(self, fp):
        h1 = fp.fingerprint_script("hello  world")
        h2 = fp.fingerprint_script("hello world")
        assert h1 == h2

    def test_different_text_different_hash(self, fp):
        h1 = fp.fingerprint_script("hello")
        h2 = fp.fingerprint_script("world")
        assert h1 != h2

    def test_empty_string(self, fp):
        h = fp.fingerprint_script("")
        assert isinstance(h, str) and len(h) > 0


class TestStructureFingerprint:
    def test_deterministic(self, fp):
        h1 = fp.fingerprint_structure(3.0, 5, ["cut", "fade"])
        h2 = fp.fingerprint_structure(3.0, 5, ["cut", "fade"])
        assert h1 == h2

    def test_order_independent(self, fp):
        h1 = fp.fingerprint_structure(3.0, 5, ["fade", "cut"])
        h2 = fp.fingerprint_structure(3.0, 5, ["cut", "fade"])
        assert h1 == h2

    def test_different_params(self, fp):
        h1 = fp.fingerprint_structure(3.0, 5, ["cut"])
        h2 = fp.fingerprint_structure(4.0, 5, ["cut"])
        assert h1 != h2

    def test_truncated_hash(self, fp):
        h = fp.fingerprint_structure(1.0, 1, [])
        assert len(h) == 16


class TestBuildFingerprint:
    def test_full_build(self, fp):
        result = fp.build_fingerprint(
            video_id="v1", script_text="hello world",
            intro_duration=3.0, scene_count=5,
            transition_types=["cut", "fade"],
        )
        assert isinstance(result, ContentFingerprint)
        assert result.video_id == "v1"
        assert result.script_hash != ""
        assert result.structure_signature != ""

    def test_minimal_build(self, fp):
        result = fp.build_fingerprint(video_id="v2")
        assert result.script_hash == ""
        assert result.visual_hashes == []
        assert result.audio_fingerprint == ""


class TestDuplicateCheck:
    def test_no_duplicates(self, fp):
        new = ContentFingerprint(video_id="v1", script_hash="abc")
        existing = [ContentFingerprint(video_id="v2", script_hash="xyz")]
        assert fp.check_duplicate(new, existing) is None

    def test_finds_duplicate(self, fp):
        target = ContentFingerprint(
            video_id="v1", script_hash="abc", visual_hashes=["h1"],
            audio_fingerprint="a", music_fingerprint="m", structure_signature="s",
        )
        existing = [ContentFingerprint(
            video_id="v2", script_hash="abc", visual_hashes=["h1"],
            audio_fingerprint="a", music_fingerprint="m", structure_signature="s",
        )]
        result = fp.check_duplicate(target, existing)
        assert result is not None
        assert result.video_id == "v2"

    def test_empty_existing(self, fp):
        new = ContentFingerprint(video_id="v1")
        assert fp.check_duplicate(new, []) is None

    def test_custom_threshold(self, fp):
        new = ContentFingerprint(video_id="v1", script_hash="abc")
        existing = [ContentFingerprint(video_id="v2", script_hash="abc")]
        assert fp.check_duplicate(new, existing, threshold=0.1) is not None
        assert fp.check_duplicate(new, existing, threshold=0.5) is None
