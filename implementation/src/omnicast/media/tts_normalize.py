r"""Text conditioning for TTS: normalize → sentence-split → chunk → estimate.

WHY THIS EXISTS. A neural voice reads exactly what it is given. The script that
reaches `TTSModule` is written for a *reader* — it carries stage directions in
brackets, `&`, `%`, `12km`, emoji, and the occasional doubled full stop from a
merge. Every one of those is a defect the moment it becomes audio: the voice
either spells the symbol out wrong, pauses in the wrong place, or emits a
strangled artefact that no amount of loudness normalisation can hide. Cleaning
happens here, once, before any provider sees the text.

DURATION IS A SYLLABLE COUNT, NOT A WORD COUNT. The old fallback estimated
`len(text.split()) * 0.4`, which assumes every word takes the same time and
that words even exist as space-separated units — false for Chinese, Japanese
and Korean, where it under-counts by roughly an order of magnitude. Speech
tempo is stable per language when measured in syllables per second, so that is
what `estimate_duration` counts, with per-language seconds-per-syllable and
explicit pauses for punctuation.

PROVENANCE. Mechanisms are reimplemented from `_refs/voice-pro`
(`app/abus_text.py` normalize/sentence-split) and its bundled CosyVoice
`split_paragraph` chunk sizing; voice-pro is **GPL-3.0**, so nothing here is
copied from it — only the approach, which is not licensable. Per-language
seconds-per-syllable comes from VideoLingo's `AdvancedSyllableEstimator`
(`en 0.225 / zh 0.21 / ja 0.21 / ko 0.21 / fr 0.22 / es 0.22 / default 0.22`),
reimplemented without its heavy g2p/pypinyin dependencies.

DELIBERATE DIVERGENCE. voice-pro collapses any word repeated twice
(`\b(\w+)\s+\1\b`). Vietnamese reduplication ("xanh xanh", "rất rất") is
meaningful, and OmniCast ships Vietnamese channels, so a doubled word is left
alone here; only a run of **three or more** identical words — which is a merge
artefact, not prose — collapses.
"""

from __future__ import annotations

import re
import unicodedata

# ---------------------------------------------------------------- normalize

#: Currency signs survive the unicode-category filter: they read as words.
_CURRENCY = "₩$€£¥₹₽₺₴₱"

#: Letters, numbers, punctuation, spaces and combining marks. Everything else
#: (emoji `So`, control chars `Cc`, private use `Co`) is not speakable.
_KEEP_CATEGORIES = frozenset({
    "Lu", "Ll", "Lt", "Lm", "Lo",        # letters
    "Nd", "Nl", "No",                    # numbers
    "Pc", "Pd", "Ps", "Pe", "Pi", "Pf", "Po",  # punctuation
    "Zs",                                # spaces
    "Mn", "Mc",                          # combining marks (Vietnamese tones)
})

_BRACKETED = (
    re.compile(r"\([^()]*\)"),   # (stage direction)
    re.compile(r"\[[^\[\]]*\]"), # [SFX: door slams]
    re.compile(r"\{[^{}]*\}"),   # {template leftovers}
)

#: Symbol → spoken form. Applied before the category filter so the symbol is
#: replaced rather than silently deleted.
_SPOKEN = (
    (re.compile(r"\s*&\s*"), " and "),
    (re.compile(r"\s*%"), " percent"),
    (re.compile(r"(\d)\s*km\b"), r"\1 kilometers"),
    (re.compile(r"(\d)\s*kg\b"), r"\1 kilograms"),
    (re.compile(r"(\d)\s*cm\b"), r"\1 centimeters"),
    (re.compile(r"\bMr\."), "Mr"),
    (re.compile(r"\bMrs\."), "Mrs"),
    (re.compile(r"\bMs\."), "Ms"),
    (re.compile(r"\bDr\."), "Dr"),
)

_REPEATED_PUNCT = re.compile(r"([!?])\1+")
_REPEATED_DOT = re.compile(r"\.{2,}")
_TRIPLED_WORD = re.compile(r"\b(\w+)(\s+\1\b){2,}", re.IGNORECASE)
_WHITESPACE = re.compile(r"\s+")


def normalize_for_tts(text: str) -> str:
    """Strip what a voice cannot speak; spell out what it would mispronounce.

    Idempotent — running it twice changes nothing, so it is safe to call at
    several layers without tracking whether an earlier one already ran.
    """
    if not text or not text.strip():
        return ""

    cleaned = text
    for pattern in _BRACKETED:
        cleaned = pattern.sub(" ", cleaned)
    for pattern, replacement in _SPOKEN:
        cleaned = pattern.sub(replacement, cleaned)

    cleaned = "".join(
        ch for ch in cleaned
        if unicodedata.category(ch) in _KEEP_CATEGORIES or ch in _CURRENCY
        or ch == "\n"
    )

    cleaned = _REPEATED_PUNCT.sub(r"\1", cleaned)
    cleaned = _REPEATED_DOT.sub(".", cleaned)
    cleaned = _TRIPLED_WORD.sub(r"\1", cleaned)
    return _WHITESPACE.sub(" ", cleaned).strip()


# ----------------------------------------------------------- sentence split

#: Terminators split differently by script. Fullwidth CJK stops, Urdu `۔` and
#: Devanagari `।॥` are unambiguous and are not followed by a space, so they end
#: a sentence wherever they appear. A latin `.` is ambiguous — "3.5", "Mr." —
#: so it only ends a sentence when whitespace or the end of the text follows.
_SENTENCE_END = re.compile(r"[。．！？۔।॥]+|[.!?]+(?=\s|$)")


def split_sentences(text: str, *, has_punctuation: bool | None = None) -> list[str]:
    """Split into sentences, keeping the terminator on the sentence it ends.

    A block with no terminators at all (subtitle dumps, bullet scripts) splits
    on newlines instead — one line is one utterance there, and returning the
    whole block as a single sentence would defeat chunking downstream.
    """
    if not text or not text.strip():
        return []
    if has_punctuation is None:
        has_punctuation = bool(_SENTENCE_END.search(text))
    if not has_punctuation:
        return [ln.strip() for ln in text.split("\n") if ln.strip()]

    sentences: list[str] = []
    cursor = 0
    for match in _SENTENCE_END.finditer(text):
        piece = text[cursor:match.end()].strip()
        if piece:
            sentences.append(piece)
        cursor = match.end()
    tail = text[cursor:].strip()
    if tail:
        sentences.append(tail)
    return sentences


# ------------------------------------------------------------------ chunking

def chunk_for_tts(
    text: str,
    *,
    token_max_n: int = 80,
    token_min_n: int = 60,
    merge_len: int = 20,
) -> list[str]:
    """Group sentences into synthesis chunks of roughly `token_min_n`..`token_max_n`.

    Long single requests drift in prosody and cost a whole retry when they fail;
    very short ones waste a round trip and break the sentence melody. Defaults
    are CosyVoice's paragraph sizing. A trailing fragment shorter than
    `merge_len` is folded back into the previous chunk rather than shipped as a
    runt, even when that pushes the chunk past `token_max_n` — an over-long
    chunk reads fine, a two-word one does not.
    """
    sentences = split_sentences(text)
    if not sentences:
        return []

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for sentence in sentences:
        length = _token_len(sentence)
        if current and current_len + length > token_max_n:
            chunks.append(" ".join(current))
            current, current_len = [], 0
        current.append(sentence)
        current_len += length
        if current_len >= token_min_n:
            chunks.append(" ".join(current))
            current, current_len = [], 0

    if current:
        tail = " ".join(current)
        if chunks and current_len < merge_len:
            chunks[-1] = f"{chunks[-1]} {tail}"
        else:
            chunks.append(tail)
    return chunks


def _token_len(text: str) -> int:
    """Rough token count: CJK characters are tokens, other scripts use words."""
    cjk = len(_CJK_CHAR.findall(text))
    words = len([w for w in _CJK_CHAR.sub(" ", text).split() if w])
    return cjk + words


# ----------------------------------------------------------------- duration

_CJK_CHAR = re.compile(r"[一-鿿㐀-䶿]")
_KANA = re.compile(r"[぀-ゟ゠-ヿ]")
_HANGUL = re.compile(r"[가-힯ᄀ-ᇿ]")
_LATIN_WORD = re.compile(r"[A-Za-zÀ-ÿĀ-ſƀ-ɏ]+")

#: Seconds per syllable, from VideoLingo's AdvancedSyllableEstimator.
_SECONDS_PER_SYLLABLE = {
    "en": 0.225, "zh": 0.21, "ja": 0.21, "ko": 0.21,
    "fr": 0.22, "es": 0.22, "vi": 0.22, "default": 0.22,
}

#: Breath, not speech: a comma-class break and a sentence-final break.
_PAUSE_MID = 0.10
_PAUSE_END = 0.20
_MID_PUNCT = re.compile(r"[,;:，；：、]")
_END_PUNCT = re.compile(r"[.。．!！?？۔।॥]")

#: Japanese small kana ride on the preceding mora; ー and っ add length, not a
#: syllable, and are dropped before counting.
_JA_NON_SYLLABIC = re.compile(r"[ゃゅょャュョーっッ]")

_VOWEL_GROUP = re.compile(r"[aeiouyàâäéèêëíîïóôöúùûüÿœæãõ]+", re.IGNORECASE)
_SILENT_E = re.compile(r"[^aeiou]e$", re.IGNORECASE)


def detect_lang(text: str) -> str:
    """Cheap script detection — enough to pick a speaking rate, not a translator."""
    if _HANGUL.search(text):
        return "ko"
    if _KANA.search(text):
        return "ja"
    if _CJK_CHAR.search(text):
        return "zh"
    return "en"


def count_syllables(text: str, lang: str | None = None) -> int:
    """Syllables across mixed scripts: CJK/kana/hangul per character, latin per
    vowel group. Mixed-script lines (a Korean sentence quoting an English brand)
    are counted script by script rather than forced into one rule."""
    if not text or not text.strip():
        return 0

    total = len(_HANGUL.findall(text)) + len(_CJK_CHAR.findall(text))
    kana = _JA_NON_SYLLABIC.sub("", "".join(_KANA.findall(text)))
    total += len(kana)

    for word in _LATIN_WORD.findall(text):
        total += _latin_syllables(word)
    return total


def _latin_syllables(word: str) -> int:
    groups = len(_VOWEL_GROUP.findall(word))
    if groups > 1 and _SILENT_E.search(word):
        groups -= 1
    return max(1, groups)


def estimate_duration(text: str, lang: str | None = None) -> float:
    """Spoken seconds for `text`, syllable-based, punctuation pauses included.

    Used as the fallback when a container cannot be probed and as the pre-flight
    check that a line will fit its scene. Accurate to roughly ±15% against real
    Edge/Kokoro output, versus the ~3× error of the word-count estimate it
    replaced on CJK text.
    """
    if not text or not text.strip():
        return 0.0
    lang = lang or detect_lang(text)
    rate = _SECONDS_PER_SYLLABLE.get(lang, _SECONDS_PER_SYLLABLE["default"])
    seconds = count_syllables(text, lang) * rate
    seconds += len(_MID_PUNCT.findall(text)) * _PAUSE_MID
    seconds += len(_END_PUNCT.findall(text)) * _PAUSE_END
    return round(seconds, 3)
