"""Parse video titles into (series base title, episode number).

Reup sources are Chinese drama posts ("《红魔猩猩》第3集 #科幻") and their
Vietnamese titles ("Khỉ Đột Đỏ - Tập 3"). Backfill grouping and the
missing-episode report both hinge on extracting the episode number and a
stable base title, so this lives in one tested module instead of being
re-invented per caller.

Everything here is pure stdlib on purpose: the backfill scanner must run in
bare environments (tests, CLI on a fresh machine) without pulling media deps.
"""
from __future__ import annotations

import re
import unicodedata

# ── numerals ────────────────────────────────────────────────────────────────

_FULLWIDTH = str.maketrans("０１２３４５６７８９", "0123456789")

_ZH_DIGIT = {
    "零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
}


def _zh_num(text: str) -> int | None:
    """Chinese numeral → int, for 第十集 / 第二十三集 / 一百零五. None if unparsable."""
    if not text:
        return None
    total, current = 0, 0
    for ch in text:
        if ch in _ZH_DIGIT:
            current = current * 10 + _ZH_DIGIT[ch] if current else _ZH_DIGIT[ch]
        elif ch == "十":
            total += (current or 1) * 10
            current = 0
        elif ch == "百":
            total += (current or 1) * 100
            current = 0
        else:
            return None
    return total + current if (total + current) > 0 else None


def _to_int(raw: str) -> int | None:
    raw = raw.translate(_FULLWIDTH).strip()
    if raw.isdigit():
        return int(raw)
    return _zh_num(raw)


# ── episode extraction ──────────────────────────────────────────────────────

_NUM = r"[0-9０-９]+|[零〇一二两三四五六七八九十百]+"

# Ordered: explicit markers first, bare trailing numbers last (most ambiguous).
_EPISODE_PATTERNS: list[re.Pattern[str]] = [
    # 第3集 / 第十二话 / 第5期 / 第2部
    re.compile(rf"第\s*({_NUM})\s*[集话話期章幕回部]"),
    # Tập 3 / tập3 / EP 3 / Ep.3 / Phần 2 / Part 4 (word-ish boundary each side)
    re.compile(
        r"(?:^|[^0-9A-Za-zÀ-ỹ])"
        r"(?:EP|Ep|eP|ep|TẬP|Tập|tập|PHẦN|Phần|phần|PART|Part|part)"
        r"\s*[.:‐–-]?\s*([0-9０-９]{1,4})(?![0-9])"
    ),
    # (3) / （3） / 【3】 / [3] at end
    re.compile(r"[（(【\[]\s*([0-9０-９]{1,4})\s*[)）】\]]\s*$"),
    # P3 / P 12 (short-video part convention) — standalone token only
    re.compile(r"(?:^|\s)[Pp]\s?([0-9]{1,3})(?=\s|$)"),
    # bare trailing number: "红魔猩猩 12" / "Khỉ Đột Đỏ - 12"
    re.compile(r"[\s_\-|·．.]([0-9]{1,4})\s*$"),
]

# Numbers that are almost never an episode when they appear bare.
_SUSPICIOUS = {360, 480, 720, 1080, 2160}
_MAX_EPISODE = 3000

_HASHTAG_RE = re.compile(r"[#＃]\S+")
_BRACKET_TITLE_RE = re.compile(r"[《【]([^》】]{1,80})[》】]")


def parse_episode(title: str) -> tuple[str, int | None]:
    """Return (title with the episode marker removed, episode number or None)."""
    text = (title or "").strip()
    if not text:
        return "", None
    for i, pattern in enumerate(_EPISODE_PATTERNS):
        m = pattern.search(text)
        if not m:
            continue
        ep = _to_int(m.group(1))
        if ep is None or not (0 < ep <= _MAX_EPISODE):
            continue
        bare = i >= 3  # P-token and trailing-number patterns
        if bare and (ep in _SUSPICIOUS or 1900 <= ep <= 2100):
            continue
        cleaned = (text[: m.start()] + " " + text[m.end():]).strip()
        return cleaned, ep
    return text, None


def base_title(title: str, title_vi: str = "") -> str:
    """The series-identifying part of a title.

    《X》 wins when present — Douyin uploaders keep it stable across episodes
    while decorating the rest of the caption differently every day.
    """
    for candidate in (title or "", title_vi or ""):
        m = _BRACKET_TITLE_RE.search(candidate)
        if m:
            return m.group(1).strip()
    text, _ = parse_episode(title or title_vi or "")
    text = _HASHTAG_RE.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip(" -–—_|·.,:;~")
    return text.strip()


# ── grouping / ids ──────────────────────────────────────────────────────────

_PUNCT_RE = re.compile(r"[\W_]+", re.UNICODE)


def normalize_key(text: str) -> str:
    """Aggressive normalization for grouping: casefold, strip accents-agnostic
    punctuation and whitespace. Vietnamese diacritics are KEPT (they are
    meaningful); only separators/punctuation go."""
    text = unicodedata.normalize("NFC", text or "")
    return _PUNCT_RE.sub("", text).casefold()


def group_key(author: str, title: str, title_vi: str = "") -> str:
    """Cluster key for backfill: same author + same normalized base title."""
    base = normalize_key(base_title(title, title_vi))
    return f"{normalize_key(author)}::{base or 'khongro'}"


def series_slug(title: str, author: str = "") -> str:
    """A readable series_id. ASCII-safe; CJK titles fall back to a hash-ish tail."""
    base = base_title(title) or title or "series"
    ascii_part = re.sub(r"[^\w]+", "_", unicodedata.normalize("NFKD", base)
                        .encode("ascii", "ignore").decode("ascii")).strip("_").lower()
    if not ascii_part:
        # CJK titles survive ASCII-folding as nothing — hex the normalized
        # characters instead, so the same title always maps to the same id.
        ascii_part = "series_" + ("".join(f"{ord(c):x}" for c in normalize_key(base)[:6]) or "x")
    return ascii_part[:60] or "series"
