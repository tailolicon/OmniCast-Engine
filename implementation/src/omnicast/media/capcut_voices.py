"""CapCut / TikTok TTS voice catalog (list metadata + SDK Voice.json merge).

CapCut and TikTok share ByteDance speaker codes (``en_us_002`` = Jessie, etc.).
This module exposes a curated catalog so the dashboard and reup tools can
surface CapCut-style voices. Synthesis is handled by
``media.providers.tts_capcut`` (real CapCut common_task API + Edge/Volcengine
fallbacks).

Notes
-----
* Curated rows are offline and dependency-free.
* Full Voice.json (vendored from K07VN/capcut-tts-api) is merged when present
  so operators can pick every CapCut ``voice_type`` the SDK knows.
* Optional ``edge_fallback`` maps popular ids onto Edge neural voices for
  offline preview when CapCut API is disabled.
* Spec form: ``capcut:<speaker_id>`` (e.g. ``capcut:en_us_002``).
"""

from __future__ import annotations

from typing import Any

# (speaker_id, label, gender, lang, desc, edge_fallback|None)
# gender: female | male | character
# lang: BCP-47-ish locale tag used by the rest of the voice catalog.
_CAPCUT_VOICE_ROWS: tuple[tuple[str, str, str, str, str, str | None], ...] = (
    # ── English US — classic CapCut / TikTok female ──────────────────────────
    ("en_us_001", "Female 1", "female", "en-US",
     "Classic TikTok/CapCut female (Int. 1)", "edge:en-US-JennyNeural"),
    ("en_us_002", "Jessie", "female", "en-US",
     "Most popular CapCut female TTS (Jessie)", "edge:en-US-JennyNeural"),
    ("en_female_samc", "Empathetic", "female", "en-US",
     "Warm, empathetic CapCut female", "edge:en-US-AriaNeural"),
    ("en_female_makeup", "Beauty Guru", "female", "en-US",
     "Beauty-influencer CapCut female", "edge:en-US-AmberNeural"),
    ("en_female_richgirl", "Bestie", "female", "en-US",
     "Bestie / rich-girl CapCut female", "edge:en-US-SaraNeural"),
    ("en_female_shenna", "Debutante", "female", "en-US",
     "Debutante CapCut female", "edge:en-US-EmmaNeural"),
    ("en_female_pansino", "Varsity", "female", "en-US",
     "Varsity CapCut female", "edge:en-US-NancyNeural"),
    ("en_female_betty", "Bae", "female", "en-US",
     "Bae CapCut female", "edge:en-US-AriaNeural"),
    ("en_female_grandma", "Granny", "female", "en-US",
     "Granny character CapCut female", "edge:en-US-JennyNeural"),
    ("en_female_emotional", "Peaceful", "female", "en-US",
     "Peaceful / emotional CapCut female", "edge:en-US-AriaNeural"),
    ("en_female_f08_twinkle", "Pop Lullaby", "female", "en-US",
     "Pop lullaby singing CapCut female", None),
    ("en_female_ht_f08_newyear", "NYE 2023", "female", "en-US",
     "New Year festive CapCut female", None),
    ("en_female_ht_f08_halloween", "Opera", "female", "en-US",
     "Opera / Halloween CapCut female", None),
    ("en_female_ht_f08_glorious", "Euphoric", "female", "en-US",
     "Euphoric CapCut female", None),
    ("en_female_ht_f08_wonderful_world", "Melodrama", "female", "en-US",
     "Melodramatic CapCut female", None),
    ("en_female_f08_warmy_breeze", "Open Mic", "female", "en-US",
     "Warmy breeze / open-mic CapCut female", None),
    ("en_female_f08_salut_damour", "Cottagecore", "female", "en-US",
     "Cottagecore / Alto CapCut female", None),
    ("en_female_madam_leota", "Madame Leota", "female", "en-US",
     "Disney-style Madame Leota CapCut female", None),
    # ── English AU ───────────────────────────────────────────────────────────
    ("en_au_001", "Metro (AU Female)", "female", "en-AU",
     "Australian CapCut female", "edge:en-AU-NatashaNeural"),
    # ── English US/UK male (full catalog; filtered out by default) ───────────
    ("en_us_006", "Joey", "male", "en-US", "US male 1 (Joey)", "edge:en-US-GuyNeural"),
    ("en_us_007", "Professor", "male", "en-US", "US male 2 (Professor)", "edge:en-US-DavisNeural"),
    ("en_us_009", "Scientist", "male", "en-US", "US male 3 (Scientist)", "edge:en-US-TonyNeural"),
    ("en_us_010", "Confidence", "male", "en-US", "US male 4 (Confidence)", "edge:en-US-BrianNeural"),
    ("en_male_jomboy", "Game On", "male", "en-US", "Game On CapCut male", None),
    ("en_male_funny", "Wacky", "male", "en-US", "Wacky CapCut male", None),
    ("en_male_cody", "Serious", "male", "en-US", "Serious CapCut male", "edge:en-US-GuyNeural"),
    ("en_male_narration", "Story Teller", "male", "en-US", "Narration CapCut male", "edge:en-US-DavisNeural"),
    ("en_male_deadpool", "Mr. GoodGuy", "male", "en-US", "Deadpool-style CapCut male", None),
    ("en_male_grinch", "Trickster", "male", "en-US", "Trickster CapCut male", None),
    ("en_male_jarvis", "Alfred", "male", "en-US", "Jarvis/Alfred CapCut male", None),
    ("en_male_trevor", "Marty", "male", "en-US", "Marty CapCut male", None),
    ("en_uk_001", "Narrator (UK)", "male", "en-GB", "UK narrator CapCut male", "edge:en-GB-RyanNeural"),
    ("en_uk_003", "Male English UK", "male", "en-GB", "UK male CapCut", "edge:en-GB-RyanNeural"),
    ("en_male_ukneighbor", "Lord Cringe", "male", "en-GB", "UK neighbor CapCut male", None),
    ("en_male_ukbutler", "Mr. Meticulous", "male", "en-GB", "UK butler CapCut male", None),
    ("en_au_002", "Smooth (AU Male)", "male", "en-AU", "Australian CapCut male", "edge:en-AU-WilliamNeural"),
    # ── Disney / character (gender mixed) ────────────────────────────────────
    ("en_us_ghostface", "Ghost Face / Scream", "character", "en-US",
     "Ghost Face character CapCut voice", None),
    ("en_us_chewbacca", "Chewbacca", "character", "en-US", "Chewbacca CapCut voice", None),
    ("en_us_c3po", "C3PO", "character", "en-US", "C3PO CapCut voice", None),
    ("en_us_stitch", "Stitch", "character", "en-US", "Stitch CapCut voice", None),
    ("en_us_stormtrooper", "Stormtrooper", "character", "en-US", "Stormtrooper CapCut voice", None),
    ("en_us_rocket", "Rocket", "character", "en-US", "Rocket CapCut voice", None),
    ("en_male_ghosthost", "Ghost Host", "character", "en-US", "Ghost Host CapCut voice", None),
    ("en_male_pirate", "Pirate", "character", "en-US", "Pirate CapCut voice", None),
    # ── German ───────────────────────────────────────────────────────────────
    ("de_001", "German Female", "female", "de-DE",
     "German CapCut female", "edge:de-DE-KatjaNeural"),
    ("de_002", "German Male", "male", "de-DE",
     "German CapCut male", "edge:de-DE-ConradNeural"),
    # ── French ───────────────────────────────────────────────────────────────
    ("fr_001", "French Male 1", "male", "fr-FR", "French CapCut male 1", "edge:fr-FR-HenriNeural"),
    ("fr_002", "French Male 2", "male", "fr-FR", "French CapCut male 2", "edge:fr-FR-HenriNeural"),
    # ── Spanish ──────────────────────────────────────────────────────────────
    ("es_002", "Spanish (Spain) Male", "male", "es-ES",
     "Spain CapCut male", "edge:es-ES-AlvaroNeural"),
    ("es_mx_002", "Spanish MX Male / Warm", "male", "es-MX",
     "Mexican CapCut male (Warm)", "edge:es-MX-JorgeNeural"),
    # ── Portuguese BR ────────────────────────────────────────────────────────
    ("br_001", "Portuguese BR Female 1", "female", "pt-BR",
     "Brazilian CapCut female 1", "edge:pt-BR-FranciscaNeural"),
    ("br_003", "Portuguese BR Female 2", "female", "pt-BR",
     "Brazilian CapCut female 2", "edge:pt-BR-FranciscaNeural"),
    ("br_004", "Portuguese BR Female 3", "female", "pt-BR",
     "Brazilian CapCut female 3", "edge:pt-BR-FranciscaNeural"),
    ("br_005", "Portuguese BR Male", "male", "pt-BR",
     "Brazilian CapCut male", "edge:pt-BR-AntonioNeural"),
    ("bp_female_ivete", "Ivete Sangalo", "female", "pt-BR",
     "Ivete Sangalo CapCut female", None),
    ("bp_female_ludmilla", "Ludmilla", "female", "pt-BR",
     "Ludmilla CapCut female", None),
    ("pt_female_lhays", "Lhays Macedo", "female", "pt-BR",
     "Lhays Macedo CapCut female", None),
    ("pt_female_laizza", "Laizza", "female", "pt-BR",
     "Laizza CapCut female", None),
    ("pt_male_bueno", "Galvão Bueno", "male", "pt-BR",
     "Galvão Bueno CapCut male", None),
    # ── Indonesian ───────────────────────────────────────────────────────────
    ("id_001", "Indonesian Female", "female", "id-ID",
     "Indonesian CapCut female", "edge:id-ID-GadisNeural"),
    # ── Japanese ─────────────────────────────────────────────────────────────
    ("jp_001", "Japanese Female 1", "female", "ja-JP",
     "Japanese CapCut female 1", "edge:ja-JP-NanamiNeural"),
    ("jp_003", "Japanese Female 2", "female", "ja-JP",
     "Japanese CapCut female 2", "edge:ja-JP-NanamiNeural"),
    ("jp_005", "Japanese Female 3", "female", "ja-JP",
     "Japanese CapCut female 3", "edge:ja-JP-NanamiNeural"),
    ("jp_006", "Japanese Male", "male", "ja-JP",
     "Japanese CapCut male", "edge:ja-JP-KeitaNeural"),
    ("jp_female_fujicochan", "りーさ", "female", "ja-JP", "Japanese CapCut female りーさ", None),
    ("jp_female_hasegawariona", "世羅鈴", "female", "ja-JP", "Japanese CapCut female 世羅鈴", None),
    ("jp_female_oomaeaika", "夏絵ココ", "female", "ja-JP", "Japanese CapCut female 夏絵ココ", None),
    ("jp_female_shirou", "四郎", "female", "ja-JP", "Japanese CapCut female 四郎", None),
    ("jp_female_kaorishoji", "庄司果織", "female", "ja-JP", "Japanese CapCut female 庄司果織", None),
    ("jp_female_yagishaki", "八木沙季", "female", "ja-JP", "Japanese CapCut female 八木沙季", None),
    ("jp_female_rei", "丸山礼", "female", "ja-JP", "Japanese CapCut female 丸山礼", None),
    ("jp_female_machikoriiita", "まちこりーた", "female", "ja-JP", "Japanese CapCut female まちこりーた", None),
    ("jp_male_keiichinakano", "Morio’s Kitchen", "male", "ja-JP", "Japanese CapCut male", None),
    ("jp_male_yujinchigusa", "低音ボイス", "male", "ja-JP", "Japanese CapCut male low", None),
    ("jp_male_tamawakazuki", "玉川寿紀", "male", "ja-JP", "Japanese CapCut male", None),
    ("jp_male_hikakin", "ヒカキン", "male", "ja-JP", "Japanese CapCut male ヒカキン", None),
    ("jp_male_shuichiro", "修一朗", "male", "ja-JP", "Japanese CapCut male", None),
    ("jp_male_matsudake", "マツダ家の日常", "male", "ja-JP", "Japanese CapCut male", None),
    ("jp_male_matsuo", "モジャオ", "male", "ja-JP", "Japanese CapCut male", None),
    ("jp_male_osada", "モリスケ", "male", "ja-JP", "Japanese CapCut male", None),
    # ── Korean ───────────────────────────────────────────────────────────────
    ("kr_002", "Korean Male 1", "male", "ko-KR",
     "Korean CapCut male 1", "edge:ko-KR-InJoonNeural"),
    ("kr_003", "Korean Female", "female", "ko-KR",
     "Korean CapCut female", "edge:ko-KR-SunHiNeural"),
    ("kr_004", "Korean Male 2", "male", "ko-KR",
     "Korean CapCut male 2", "edge:ko-KR-InJoonNeural"),
    # ── Vietnamese (CapCut streaming speaker ids) ────────────────────────────
    ("BV074_streaming", "Vietnamese Female", "female", "vi-VN",
     "Vietnamese CapCut female (streaming)", "edge:vi-VN-HoaiMyNeural"),
    ("BV075_streaming", "Vietnamese Male", "male", "vi-VN",
     "Vietnamese CapCut male (streaming)", "edge:vi-VN-NamMinhNeural"),
)


def _row_to_entry(row: tuple[str, str, str, str, str, str | None]) -> dict[str, Any]:
    speaker_id, label, gender, lang, desc, edge_fallback = row
    entry: dict[str, Any] = {
        "spec": f"capcut:{speaker_id}",
        "speaker_id": speaker_id,
        "label": label,
        "gender": gender,
        "lang": lang,
        "provider": "capcut",
        "source": "capcut_tiktok",
        "desc": desc,
        "age": "",
        "pitch": "",
        "accent": "",
        "use_case": "social",
    }
    if edge_fallback:
        entry["edge_fallback"] = edge_fallback
    return entry


def curated_catalog() -> list[dict[str, Any]]:
    """Hand-curated CapCut/TikTok rows (gender + edge_fallback metadata)."""
    return [_row_to_entry(r) for r in _CAPCUT_VOICE_ROWS]


def catalog(*, include_sdk: bool = True) -> list[dict[str, Any]]:
    """Full CapCut/TikTok voice catalog (curated + optional SDK Voice.json)."""
    base = curated_catalog()
    if not include_sdk:
        return base
    try:
        from omnicast.media.providers.tts_capcut import load_sdk_catalog
    except Exception:
        return base
    by_id = {v["speaker_id"]: dict(v) for v in base}
    for row in load_sdk_catalog():
        sid = row["speaker_id"]
        if sid in by_id:
            # Prefer curated gender/fallback; fill resource_id + richer label.
            entry = by_id[sid]
            if row.get("resource_id"):
                entry["resource_id"] = row["resource_id"]
            if row.get("label") and entry.get("label") in (sid, entry.get("speaker_id")):
                entry["label"] = row["label"]
            entry.setdefault("source", "capcut_tiktok")
            continue
        by_id[sid] = dict(row)
    return list(by_id.values())


def list_capcut_voices(
    *,
    gender: str | None = "female",
    lang: str | None = None,
    q: str | None = None,
    include_sdk: bool = True,
) -> list[dict[str, Any]]:
    """Filter CapCut voices.

    Parameters
    ----------
    gender:
        ``female`` (default), ``male``, ``character``, or ``all``/``None`` for everything.
        SDK-only rows have ``gender=unknown`` and only appear when gender is
        ``all``/``None``/``unknown``.
    lang:
        Locale prefix filter (e.g. ``en``, ``en-US``, ``vi``).
    q:
        Free-text match against label / speaker_id / desc.
    include_sdk:
        Merge vendored Voice.json entries (default True).
    """
    voices = catalog(include_sdk=include_sdk)
    g = (gender or "all").strip().lower()
    if g and g not in ("all", "*", "any"):
        voices = [v for v in voices if (v.get("gender") or "").lower() == g]
    if lang:
        prefix = lang.strip().lower()
        voices = [
            v for v in voices
            if (v.get("lang") or "").lower().startswith(prefix)
        ]
    if q:
        needle = q.strip().lower()
        if needle:
            voices = [
                v for v in voices
                if needle in (v.get("label") or "").lower()
                or needle in (v.get("speaker_id") or "").lower()
                or needle in (v.get("desc") or "").lower()
                or needle in (v.get("spec") or "").lower()
            ]
    return voices


def female_voices(*, lang: str | None = None, q: str | None = None) -> list[dict[str, Any]]:
    """Convenience: CapCut female voices only."""
    return list_capcut_voices(gender="female", lang=lang, q=q)


def get_voice(speaker_id: str) -> dict[str, Any] | None:
    """Lookup one speaker by id (with or without ``capcut:`` prefix)."""
    sid = (speaker_id or "").strip()
    if sid.startswith("capcut:"):
        sid = sid.split(":", 1)[1]
    for v in catalog():
        if v["speaker_id"] == sid:
            return v
    return None
