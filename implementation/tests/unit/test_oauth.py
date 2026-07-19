import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from omnicast.upload.oauth import OAuth2Manager
from omnicast.upload.models import TokenHealth, TokenStatus
from omnicast.shared.errors import UploadPipelineError


@pytest.fixture
def oauth(tmp_path):
    from cryptography.fernet import Fernet
    key = Fernet.generate_key()
    return OAuth2Manager(token_dir=str(tmp_path), encryption_key=key.decode())


class TestOAuth2ManagerHealth:
    @pytest.mark.asyncio
    async def test_check_health_valid(self, oauth):
        with patch.object(oauth, "get_credentials", new_callable=AsyncMock) as mock_creds:
            mock_cred = MagicMock()
            mock_cred.valid = True
            mock_cred.expired = False
            mock_cred.scopes = {"https://www.googleapis.com/auth/youtube.upload"}
            mock_cred.expiry = None
            mock_creds.return_value = mock_cred
            health = await oauth.check_health("ch1")
            assert health.status == TokenStatus.VALID

    @pytest.mark.asyncio
    async def test_check_health_expired(self, oauth):
        with patch.object(oauth, "get_credentials", new_callable=AsyncMock,
                           side_effect=UploadPipelineError("Token expired")):
            health = await oauth.check_health("ch1")
            assert health.status in (TokenStatus.EXPIRED, TokenStatus.REVOKED)

    @pytest.mark.asyncio
    async def test_check_all_channels(self, oauth):
        valid = TokenHealth(channel_id="ch1", status=TokenStatus.VALID)
        expired = TokenHealth(channel_id="ch2", status=TokenStatus.EXPIRED, error="expired")
        with patch.object(oauth, "check_health", new_callable=AsyncMock, side_effect=[valid, expired]):
            results = await oauth.check_all_channels(["ch1", "ch2"])
            assert len(results) == 2
            assert results[0].status == TokenStatus.VALID
            assert results[1].status == TokenStatus.EXPIRED

    @pytest.mark.asyncio
    async def test_check_all_handles_exceptions(self, oauth):
        with patch.object(oauth, "check_health", new_callable=AsyncMock,
                           side_effect=RuntimeError("network")):
            results = await oauth.check_all_channels(["ch1"])
            assert len(results) == 1
            assert results[0].status == TokenStatus.REVOKED


class TestOAuth2ManagerStorage:
    @pytest.mark.asyncio
    async def test_store_and_load(self, oauth):
        # Test encrypt/decrypt roundtrip
        if oauth.encryption_key:
            data = b'{"access_token": "test", "refresh_token": "test2"}'
            encrypted = oauth._encrypt(data)
            assert encrypted != data
            decrypted = oauth._decrypt(encrypted)
            assert decrypted == data

    def test_generate_auth_url(self, oauth):
        url = oauth.generate_auth_url("ch1")
        assert isinstance(url, str)
        assert "oauth" in url.lower() or "auth" in url.lower() or url.startswith("http")


class TestOAuth2Manager:
    def test_token_dir_set(self, oauth, tmp_path):
        assert str(oauth.token_dir) == str(tmp_path)

    @pytest.mark.asyncio
    async def test_get_credentials_missing_token(self, oauth):
        with pytest.raises(UploadPipelineError):
            await oauth.get_credentials("nonexistent_channel")
