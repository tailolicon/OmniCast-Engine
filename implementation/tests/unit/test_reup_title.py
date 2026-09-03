"""Title translation: hashtag splitting, clamping, and failure behaviour."""

from __future__ import annotations

from omnicast.reup.translate.title import (
    MAX_TITLE_CHARS,
    TranslatedTitle,
    split_hashtags,
    translate_title,
)


class _FakeResponse:
    def __init__(self, parsed):
        self.output_parsed = parsed
        self.usage = None


class _FakeResponses:
    def __init__(self, parsed=None, error=None):
        self._parsed, self._error = parsed, error
        self.last_input = None

    def parse(self, **kwargs):
        if self._error:
            raise self._error
        self.last_input = kwargs.get("input", "")
        return _FakeResponse(self._parsed)


class _FakeEngine:
    def __init__(self, parsed=None, error=None):
        self.responses = _FakeResponses(parsed, error)

    def _build_client(self):
        return self


def test_hashtags_split_off_the_title_text():
    text, tags = split_hashtags("一口气看完《红魔猩猩》 #沙雕动画#恐怖故事#悬疑")
    assert text == "一口气看完《红魔猩猩》"
    assert tags == ["沙雕动画", "恐怖故事", "悬疑"]


def test_title_without_hashtags_is_untouched():
    assert split_hashtags("深夜十二点半") == ("深夜十二点半", [])


def test_translation_returns_title_and_tags():
    engine = _FakeEngine(TranslatedTitle(title_vi="Hồng Ma Tinh Tinh", tags_vi=["Kinh dị"]))
    result = translate_title(engine=engine, model="m", source_title="红魔猩猩 #恐怖")
    assert result.title_vi == "Hồng Ma Tinh Tinh"
    assert result.tags_vi == ["Kinh dị"]
    assert result.source_tags == ["恐怖"]


def test_sample_lines_are_given_to_the_model():
    # Without plot context the model can only transliterate the source title.
    engine = _FakeEngine(TranslatedTitle(title_vi="x"))
    translate_title(
        engine=engine, model="m", source_title="标题",
        sample_lines=["Anh còn nhớ tôi là ai không?"],
    )
    assert "Anh còn nhớ tôi là ai không?" in engine.responses.last_input


def test_trailing_full_stop_is_stripped():
    engine = _FakeEngine(TranslatedTitle(title_vi="Một tiêu đề."))
    assert translate_title(engine=engine, model="m", source_title="x").title_vi.endswith("đề")


def test_overlong_title_is_cut_on_a_word_boundary():
    long_title = "Từ " * 60
    engine = _FakeEngine(TranslatedTitle(title_vi=long_title))
    title = translate_title(engine=engine, model="m", source_title="x").title_vi
    assert len(title) <= MAX_TITLE_CHARS
    assert not title.endswith("T"), "must not cut mid-word"


def test_tags_are_deduplicated_and_stripped_of_hashes():
    engine = _FakeEngine(
        TranslatedTitle(title_vi="t", tags_vi=["#Kinh dị", "kinh dị", " Bí ẩn "])
    )
    assert translate_title(engine=engine, model="m", source_title="x").tags_vi == [
        "Kinh dị",
        "Bí ẩn",
    ]


def test_engine_failure_leaves_the_job_alive():
    # A bad title must not sink a run whose audio and subtitles are fine.
    engine = _FakeEngine(error=RuntimeError("model down"))
    result = translate_title(engine=engine, model="m", source_title="红魔猩猩 #恐怖")
    assert result.is_empty
    assert result.source_tags == ["恐怖"], "source tags survive for a manual retitle"
