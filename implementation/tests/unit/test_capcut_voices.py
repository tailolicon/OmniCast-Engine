"""CapCut / TikTok voice catalog + API endpoint tests."""

from __future__ import annotations

from fastapi.testclient import TestClient

from omnicast.media.capcut_voices import (
    catalog,
    female_voices,
    get_voice,
    list_capcut_voices,
)


class TestCapCutCatalog:
    def test_catalog_nonempty(self):
        voices = catalog()
        assert len(voices) >= 40
        assert all(v["provider"] == "capcut" for v in voices)
        assert all(v["spec"].startswith("capcut:") for v in voices)

    def test_default_filter_is_female(self):
        voices = list_capcut_voices()
        assert voices
        assert all(v["gender"] == "female" for v in voices)

    def test_female_helper(self):
        assert female_voices() == list_capcut_voices(gender="female")

    def test_jessie_present(self):
        jessie = get_voice("en_us_002")
        assert jessie is not None
        assert jessie["label"] == "Jessie"
        assert jessie["gender"] == "female"
        assert jessie["spec"] == "capcut:en_us_002"
        assert jessie.get("edge_fallback", "").startswith("edge:")

    def test_lookup_with_prefix(self):
        assert get_voice("capcut:en_us_002") == get_voice("en_us_002")

    def test_lang_filter_vi(self):
        vi = list_capcut_voices(gender="female", lang="vi")
        assert vi
        assert all(v["lang"].startswith("vi") for v in vi)
        assert any(v["speaker_id"] == "BV074_streaming" for v in vi)

    def test_search_jessie(self):
        hits = list_capcut_voices(gender="all", q="jessie")
        # Curated en_us_002 plus any SDK Voice.json rows that also say Jessie.
        assert hits
        ids = {v["speaker_id"] for v in hits}
        assert "en_us_002" in ids

    def test_gender_all(self):
        all_v = list_capcut_voices(gender="all")
        genders = {v["gender"] for v in all_v}
        assert "female" in genders
        assert "male" in genders


def _make_client() -> TestClient:
    from omnicast.api.server import app
    return TestClient(app)


class TestCapCutVoiceEndpoints:
    def test_list_female_default(self):
        client = _make_client()
        r = client.get("/api/voices/capcut")
        assert r.status_code == 200
        data = r.json()
        assert data["count"] > 0
        assert data["provider"] == "capcut"
        assert data["gender"] == "female"
        assert all(v["gender"] == "female" for v in data["voices"])
        # Jessie must be in the default female list
        ids = {v["speaker_id"] for v in data["voices"]}
        assert "en_us_002" in ids

    def test_tiktok_alias(self):
        client = _make_client()
        r = client.get("/api/tiktok/voices?gender=female&lang=en-US")
        assert r.status_code == 200
        data = r.json()
        assert data["count"] > 0
        assert all(v["lang"].startswith("en-US") for v in data["voices"])

    def test_get_one(self):
        client = _make_client()
        r = client.get("/api/voices/capcut/en_us_002")
        assert r.status_code == 200
        assert r.json()["label"] == "Jessie"

    def test_get_missing(self):
        client = _make_client()
        r = client.get("/api/voices/capcut/not_a_real_voice")
        assert r.status_code == 404

    def test_include_capcut_in_full_catalog(self):
        client = _make_client()
        r = client.get("/api/voices?include_capcut=true")
        assert r.status_code == 200
        data = r.json()
        assert data["providers"].get("capcut") is True
        assert any(v.get("provider") == "capcut" for v in data["voices"])
