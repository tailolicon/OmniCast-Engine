"""Translate the source video's title into a publishable Vietnamese one.

A Douyin title is not a sentence to translate literally — it is a packed hook
plus a tail of hashtags:

    一口气看完《红魔猩猩》 #沙雕动画#恐怖故事#睡前故事#悬疑#细思极恐

Translating that word-for-word gives something no Vietnamese viewer would click.
So the hashtags are split off and handled separately from the title text, and
the title itself is rewritten as a title rather than transliterated.

Runs through the same engine as the body translation, so a job that costs
nothing to translate also costs nothing to title.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from pydantic import BaseModel, Field

# Douyin packs tags on the end with no spaces: "#沙雕动画#恐怖故事#悬疑".
_HASHTAG = re.compile(r"#([^#\s]+)")

# YouTube truncates around here in most surfaces.
MAX_TITLE_CHARS = 90


class TranslatedTitle(BaseModel):
    title_vi: str = Field(description="Vietnamese title, natural and clickable")
    tags_vi: list[str] = Field(default_factory=list, description="Vietnamese tags")


@dataclass(slots=True)
class TitleTranslation:
    source_title: str
    title_vi: str
    tags_vi: list[str] = field(default_factory=list)
    source_tags: list[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.title_vi.strip()


def split_hashtags(raw_title: str) -> tuple[str, list[str]]:
    """Separate the title text from its trailing hashtags."""
    tags = [t.strip() for t in _HASHTAG.findall(raw_title or "") if t.strip()]
    text = _HASHTAG.sub(" ", raw_title or "")
    return " ".join(text.split()), tags


_SYSTEM_PROMPT = """\
Bạn đặt tiêu đề video tiếng Việt cho kênh đăng lại nội dung Trung Quốc.

Đầu vào là tiêu đề gốc tiếng Trung (đã tách hashtag) kèm vài câu thoại đầu video
để bạn nắm nội dung.

Yêu cầu tiêu đề:
- Tiếng Việt tự nhiên, KHÔNG dịch máy, KHÔNG phiên âm bừa.
- Giữ đúng nội dung thật của video; không hứa điều video không có.
- Tên riêng dùng Hán-Việt nếu có dạng quen thuộc, không dùng pinyin.
- Tối đa {max_chars} ký tự, không kết thúc bằng dấu chấm.
- Viết hoa như tiêu đề bình thường: hoa chữ đầu câu và mọi danh từ riêng.
  KHÔNG viết thường toàn bộ, cũng KHÔNG VIẾT HOA TOÀN BỘ.
- Không thêm emoji.

Tags: dịch mỗi hashtag gốc sang tiếng Việt ngắn gọn, bỏ hashtag vô nghĩa hoặc
trùng lặp. Không thêm dấu # vào kết quả.
"""


def build_title_prompt(
    *, source_title: str, source_tags: list[str], sample_lines: list[str]
) -> tuple[str, str]:
    """Return (system, user) for the title call."""
    lines = "\n".join(f"- {line}" for line in sample_lines[:8] if line.strip())
    tags = ", ".join(source_tags) if source_tags else "(không có)"
    user = (
        f"Tiêu đề gốc: {source_title or '(trống)'}\n"
        f"Hashtag gốc: {tags}\n\n"
        f"Vài câu đầu video:\n{lines or '- (không có)'}"
    )
    return _SYSTEM_PROMPT.format(max_chars=MAX_TITLE_CHARS), user


def translate_title(
    *,
    engine,
    model: str,
    source_title: str,
    sample_lines: list[str] | None = None,
) -> TitleTranslation:
    """Translate one title. Falls back to the source on any engine failure.

    A bad title should not sink a job whose audio and subtitles are fine — the
    operator can always retitle, but they cannot un-fail a pipeline run.
    """
    text, source_tags = split_hashtags(source_title)
    system, user = build_title_prompt(
        source_title=text, source_tags=source_tags, sample_lines=sample_lines or []
    )

    try:
        client = engine._build_client()  # noqa: SLF001 - same seam the stages use
        response = client.responses.parse(
            model=model,
            instructions=system,
            input=user,
            text_format=TranslatedTitle,
            temperature=0.4,
        )
        parsed = response.output_parsed
    except Exception:
        return TitleTranslation(
            source_title=source_title,
            title_vi="",
            tags_vi=[],
            source_tags=source_tags,
        )

    title = (parsed.title_vi or "").strip().rstrip(".")
    if len(title) > MAX_TITLE_CHARS:
        # Cut on a word boundary rather than mid-syllable.
        title = title[:MAX_TITLE_CHARS].rsplit(" ", 1)[0]

    seen: set[str] = set()
    tags: list[str] = []
    for tag in parsed.tags_vi or []:
        cleaned = tag.strip().lstrip("#").strip()
        key = cleaned.lower()
        if cleaned and key not in seen:
            seen.add(key)
            tags.append(cleaned)

    return TitleTranslation(
        source_title=source_title,
        title_vi=title,
        tags_vi=tags,
        source_tags=source_tags,
    )
