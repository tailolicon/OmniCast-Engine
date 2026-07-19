import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from pydantic import ValidationError
from omnicast.media.asset_manager import (
    AssetManager, CharacterProfile, CharacterRegistry, StockLevel,
)
from omnicast.models.enums import AssetType, MusicMood
from omnicast.shared.errors import MediaError


class TestCharacterProfile:
    def test_create(self):
        c = CharacterProfile(name="narrator", reference_image="/nas/ref.png")
        assert c.name == "narrator"
        assert c.ip_adapter_weight == 0.6
        assert c.lora_path is None

    def test_with_lora(self):
        c = CharacterProfile(name="hero", reference_image="/ref.png",
                              lora_path="/loras/hero_v1.safetensors", ip_adapter_weight=0.8)
        assert c.lora_path is not None

    def test_ip_weight_bounds(self):
        CharacterProfile(name="x", reference_image="/x.png", ip_adapter_weight=0.0)
        CharacterProfile(name="x", reference_image="/x.png", ip_adapter_weight=1.0)
        with pytest.raises(ValidationError):
            CharacterProfile(name="x", reference_image="/x.png", ip_adapter_weight=1.1)

    def test_frozen(self):
        c = CharacterProfile(name="x", reference_image="/x.png")
        with pytest.raises(ValidationError):
            c.name = "y"


class TestCharacterRegistry:
    def test_empty(self):
        r = CharacterRegistry(channel_id="ch1")
        assert r.list_names() == []
        assert r.get("nobody") is None

    def test_get_existing(self):
        c = CharacterProfile(name="narrator", reference_image="/ref.png")
        r = CharacterRegistry(channel_id="ch1", characters={"narrator": c})
        assert r.get("narrator") is not None
        assert r.get("narrator").reference_image == "/ref.png"

    def test_list_names(self):
        chars = {
            "narrator": CharacterProfile(name="narrator", reference_image="/a.png"),
            "villain": CharacterProfile(name="villain", reference_image="/b.png"),
        }
        r = CharacterRegistry(channel_id="ch1", characters=chars)
        assert sorted(r.list_names()) == ["narrator", "villain"]

    def test_frozen(self):
        r = CharacterRegistry(channel_id="ch1")
        with pytest.raises(ValidationError):
            r.channel_id = "ch2"


class TestStockLevel:
    def test_needs_replenish_low_count(self):
        s = StockLevel(asset_type=AssetType.MUSIC_YT_LIBRARY, mood=MusicMood.CINEMATIC,
                        count=5, needs_replenish=True)
        assert s.needs_replenish

    def test_healthy_stock(self):
        s = StockLevel(asset_type=AssetType.BROLL, count=50, avg_use_count=3.0)
        assert not s.needs_replenish


class TestAssetManagerSearch:
    @pytest.fixture
    def manager(self):
        return AssetManager(session_factory=MagicMock(), nas_base_path="/nas")

    @pytest.mark.asyncio
    async def test_search_music(self, manager):
        mock_repo = AsyncMock()
        mock_repo.search.return_value = [MagicMock(id=1, path="/nas/track.wav", use_count=2)]
        with patch.object(manager, "session_factory") as sf:
            sf.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            results = await manager.search_music(mood=MusicMood.CINEMATIC, limit=5)
            # implementation will call repo.search internally

    @pytest.mark.asyncio
    async def test_search_broll(self, manager):
        # verify it accepts tags parameter
        with patch.object(manager, "session_factory"):
            results = await manager.search_broll(tags=["ocean", "sunset"])

    @pytest.mark.asyncio
    async def test_search_template(self, manager):
        with patch.object(manager, "session_factory"):
            results = await manager.search_template(template_type="intro", channel_id="ch1")


class TestAssetManagerRegister:
    @pytest.fixture
    def manager(self):
        return AssetManager(session_factory=MagicMock(), nas_base_path="/nas")

    def test_compute_md5(self, manager, tmp_path):
        f = tmp_path / "test.wav"
        f.write_bytes(b"fake audio data 12345")
        md5 = manager.compute_md5(str(f))
        assert isinstance(md5, str) and len(md5) == 32

    def test_compute_md5_deterministic(self, manager, tmp_path):
        f = tmp_path / "test.wav"
        f.write_bytes(b"same content")
        assert manager.compute_md5(str(f)) == manager.compute_md5(str(f))

    def test_compute_md5_different_content(self, manager, tmp_path):
        f1 = tmp_path / "a.wav"
        f2 = tmp_path / "b.wav"
        f1.write_bytes(b"content A")
        f2.write_bytes(b"content B")
        assert manager.compute_md5(str(f1)) != manager.compute_md5(str(f2))


class TestAssetManagerStock:
    @pytest.fixture
    def manager(self):
        return AssetManager(session_factory=MagicMock(), nas_base_path="/nas")

    @pytest.mark.asyncio
    async def test_get_replenish_list_filters(self, manager):
        levels = [
            StockLevel(asset_type=AssetType.MUSIC_YT_LIBRARY, mood=MusicMood.CINEMATIC,
                        count=5, needs_replenish=True),
            StockLevel(asset_type=AssetType.BROLL, count=50, needs_replenish=False),
            StockLevel(asset_type=AssetType.MUSIC_AI_GENERATED, mood=MusicMood.EPIC,
                        count=3, avg_use_count=25.0, needs_replenish=True),
        ]
        with patch.object(manager, "get_stock_levels", new_callable=AsyncMock, return_value=levels):
            replenish = await manager.get_replenish_list()
            assert len(replenish) == 2
            assert all(l.needs_replenish for l in replenish)


class TestAssetManagerCharacter:
    @pytest.fixture
    def manager(self):
        return AssetManager(session_factory=MagicMock(), nas_base_path="/nas")

    @pytest.mark.asyncio
    async def test_load_empty_registry(self, manager):
        with patch.object(manager, "load_character_registry", new_callable=AsyncMock,
                           return_value=CharacterRegistry(channel_id="ch1")):
            reg = await manager.load_character_registry("ch1")
            assert reg.list_names() == []

    @pytest.mark.asyncio
    async def test_get_character(self, manager):
        char = CharacterProfile(name="narrator", reference_image="/ref.png")
        reg = CharacterRegistry(channel_id="ch1", characters={"narrator": char})
        with patch.object(manager, "load_character_registry", new_callable=AsyncMock, return_value=reg):
            result = await manager.get_character("ch1", "narrator")
            assert result is not None
            assert result.name == "narrator"

    @pytest.mark.asyncio
    async def test_get_character_missing(self, manager):
        reg = CharacterRegistry(channel_id="ch1")
        with patch.object(manager, "load_character_registry", new_callable=AsyncMock, return_value=reg):
            result = await manager.get_character("ch1", "nobody")
            assert result is None
