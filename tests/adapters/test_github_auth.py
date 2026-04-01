"""Tests for GitHub OAuth credential storage (github_auth adapter)."""

from __future__ import annotations

import asyncio
import platform
from pathlib import Path
from typing import Any

import httpx
import pytest
from beddel_auth_github.provider import (
    CredentialData,
    check_token_validity,
    delete_credentials,
    get_auth_headers,
    get_github_user,
    initiate_device_flow,
    load_credentials,
    poll_for_token,
    save_credentials,
)

from beddel.domain.errors import BeddelError


@pytest.fixture()
def _patch_creds_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect CREDENTIALS_PATH to a tmp_path file for test isolation."""
    creds = tmp_path / "credentials.json"
    monkeypatch.setattr("beddel_auth_github.provider.CREDENTIALS_PATH", creds)
    return creds


def _sample_data() -> CredentialData:
    return CredentialData(
        access_token="gho_abc123",
        github_user="testuser",
        server_url=None,
        created_at="2026-03-27T00:00:00Z",
    )


class TestSaveAndLoadCredentials:
    """Round-trip save → load tests."""

    def test_save_and_load_credentials(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        creds = tmp_path / "credentials.json"
        monkeypatch.setattr("beddel_auth_github.provider.CREDENTIALS_PATH", creds)
        data = _sample_data()

        save_credentials(data)
        loaded = load_credentials()

        assert loaded is not None
        assert loaded["access_token"] == data["access_token"]
        assert loaded["github_user"] == data["github_user"]
        assert loaded["server_url"] == data["server_url"]
        assert loaded["created_at"] == data["created_at"]


class TestLoadNonexistent:
    """load_credentials when no file exists."""

    def test_load_nonexistent_returns_none(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        creds = tmp_path / "credentials.json"
        monkeypatch.setattr("beddel_auth_github.provider.CREDENTIALS_PATH", creds)

        assert load_credentials() is None


class TestDeleteCredentials:
    """delete_credentials tests."""

    def test_delete_credentials(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        creds = tmp_path / "credentials.json"
        monkeypatch.setattr("beddel_auth_github.provider.CREDENTIALS_PATH", creds)
        save_credentials(_sample_data())
        assert creds.exists()

        result = delete_credentials()

        assert result is True
        assert not creds.exists()

    def test_delete_nonexistent_returns_false(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        creds = tmp_path / "credentials.json"
        monkeypatch.setattr("beddel_auth_github.provider.CREDENTIALS_PATH", creds)

        assert delete_credentials() is False


class TestSaveCreatesParentDirs:
    """save_credentials creates parent directories."""

    def test_save_creates_parent_dirs(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        creds = tmp_path / "nested" / "deep" / "credentials.json"
        monkeypatch.setattr("beddel_auth_github.provider.CREDENTIALS_PATH", creds)

        save_credentials(_sample_data())

        assert creds.exists()
        assert creds.parent.is_dir()


@pytest.mark.skipif(platform.system() == "Windows", reason="chmod 0o600 not meaningful on Windows")
class TestSaveSetsPermissions:
    """save_credentials sets 0o600 permissions on the file."""

    def test_save_sets_permissions(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        creds = tmp_path / "credentials.json"
        monkeypatch.setattr("beddel_auth_github.provider.CREDENTIALS_PATH", creds)

        save_credentials(_sample_data())

        file_mode = creds.stat().st_mode & 0o777
        assert file_mode == 0o600


class TestSaveErrorHandling:
    """save_credentials raises BeddelError on failure."""

    def test_save_raises_on_write_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Point to a path inside a file (impossible to mkdir)
        bad_path = tmp_path / "afile"
        bad_path.write_text("block")
        creds = bad_path / "credentials.json"
        monkeypatch.setattr("beddel_auth_github.provider.CREDENTIALS_PATH", creds)

        with pytest.raises(BeddelError) as exc_info:
            save_credentials(_sample_data())
        assert "BEDDEL-AUTH-904" in str(exc_info.value)


class TestLoadErrorHandling:
    """load_credentials raises BeddelError on parse errors."""

    def test_load_raises_on_invalid_json(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        creds = tmp_path / "credentials.json"
        creds.write_text("{invalid json")
        monkeypatch.setattr("beddel_auth_github.provider.CREDENTIALS_PATH", creds)

        with pytest.raises(BeddelError) as exc_info:
            load_credentials()
        assert "BEDDEL-AUTH-904" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Device Flow tests (Task 3)
# ---------------------------------------------------------------------------

# Capture the real class before any monkeypatching.
_RealAsyncClient = httpx.AsyncClient


def _mock_client(handler: Any) -> Any:
    """Build a factory that returns an AsyncClient with a MockTransport."""

    def factory(**kw: Any) -> httpx.AsyncClient:  # type: ignore[type-arg]
        return _RealAsyncClient(transport=httpx.MockTransport(handler))

    return factory


async def _noop_sleep(_seconds: float) -> None:
    """No-op replacement for asyncio.sleep in tests."""


class TestInitiateDeviceFlowSuccess:
    """initiate_device_flow returns parsed JSON on 200."""

    @pytest.mark.asyncio
    async def test_initiate_device_flow_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        expected: dict[str, Any] = {
            "device_code": "dc_abc",
            "user_code": "ABCD-1234",
            "verification_uri": "https://github.com/login/device",
            "expires_in": 900,
            "interval": 5,
        }

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=expected)

        monkeypatch.setattr(httpx, "AsyncClient", _mock_client(handler))

        result = await initiate_device_flow("test-client-id")
        assert result == expected


class TestInitiateDeviceFlowFailure:
    """initiate_device_flow raises BeddelError on non-200."""

    @pytest.mark.asyncio
    async def test_initiate_device_flow_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(400, json={"error": "bad_request"})

        monkeypatch.setattr(httpx, "AsyncClient", _mock_client(handler))

        with pytest.raises(BeddelError) as exc_info:
            await initiate_device_flow("test-client-id")
        assert "BEDDEL-AUTH-901" in str(exc_info.value)


class TestPollForTokenSuccess:
    """poll_for_token returns access_token after pending → success."""

    @pytest.mark.asyncio
    async def test_poll_for_token_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                return httpx.Response(200, json={"error": "authorization_pending"})
            return httpx.Response(200, json={"access_token": "gho_tok123"})

        monkeypatch.setattr(httpx, "AsyncClient", _mock_client(handler))
        monkeypatch.setattr(asyncio, "sleep", _noop_sleep)

        token = await poll_for_token("cid", "dc", interval=1, expires_in=60)
        assert token == "gho_tok123"
        assert call_count == 3


class TestPollForTokenTimeout:
    """poll_for_token raises AUTH_DEVICE_FLOW_TIMEOUT on expired_token."""

    @pytest.mark.asyncio
    async def test_poll_for_token_timeout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"error": "expired_token"})

        monkeypatch.setattr(httpx, "AsyncClient", _mock_client(handler))
        monkeypatch.setattr(asyncio, "sleep", _noop_sleep)

        with pytest.raises(BeddelError) as exc_info:
            await poll_for_token("cid", "dc", interval=1, expires_in=60)
        assert "BEDDEL-AUTH-902" in str(exc_info.value)


class TestPollForTokenSlowDown:
    """poll_for_token increases interval by 5s on slow_down."""

    @pytest.mark.asyncio
    async def test_poll_for_token_slow_down(self, monkeypatch: pytest.MonkeyPatch) -> None:
        call_count = 0
        sleep_values: list[float] = []

        async def tracking_sleep(seconds: float) -> None:
            sleep_values.append(seconds)

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return httpx.Response(200, json={"error": "slow_down"})
            return httpx.Response(200, json={"access_token": "gho_tok456"})

        monkeypatch.setattr(httpx, "AsyncClient", _mock_client(handler))
        monkeypatch.setattr(asyncio, "sleep", tracking_sleep)

        token = await poll_for_token("cid", "dc", interval=5, expires_in=120)
        assert token == "gho_tok456"
        # First sleep at interval=5, second sleep at interval=10 (5+5)
        assert sleep_values[0] == 5
        assert sleep_values[1] == 10


class TestGetGithubUserSuccess:
    """get_github_user returns login on 200."""

    @pytest.mark.asyncio
    async def test_get_github_user_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"login": "octocat", "id": 1})

        monkeypatch.setattr(httpx, "AsyncClient", _mock_client(handler))

        login = await get_github_user("gho_tok")
        assert login == "octocat"


class TestGetGithubUserFailure:
    """get_github_user raises BeddelError on non-200."""

    @pytest.mark.asyncio
    async def test_get_github_user_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"message": "Bad credentials"})

        monkeypatch.setattr(httpx, "AsyncClient", _mock_client(handler))

        with pytest.raises(BeddelError) as exc_info:
            await get_github_user("bad_token")
        assert "BEDDEL-AUTH-903" in str(exc_info.value)


# ---------------------------------------------------------------------------
# get_auth_headers / check_token_validity tests (Story 4.0A.4, Task 1)
# ---------------------------------------------------------------------------


class TestGetAuthHeadersWithCredentials:
    """get_auth_headers returns Bearer header when credentials have server_url."""

    def test_get_auth_headers_with_credentials(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        creds = tmp_path / "credentials.json"
        monkeypatch.setattr("beddel_auth_github.provider.CREDENTIALS_PATH", creds)
        save_credentials(
            CredentialData(
                access_token="gho_abc123",
                github_user="testuser",
                server_url="https://dash.example.com",
                created_at="2026-03-27T00:00:00Z",
            )
        )

        headers = get_auth_headers()
        assert headers is not None
        assert headers == {"Authorization": "Bearer gho_abc123"}


class TestGetAuthHeadersNoCredentials:
    """get_auth_headers returns None when no credentials file exists."""

    def test_get_auth_headers_no_credentials(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        creds = tmp_path / "credentials.json"
        monkeypatch.setattr("beddel_auth_github.provider.CREDENTIALS_PATH", creds)

        assert get_auth_headers() is None


class TestGetAuthHeadersNoServerUrl:
    """get_auth_headers returns None when credentials lack server_url."""

    def test_get_auth_headers_no_server_url(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        creds = tmp_path / "credentials.json"
        monkeypatch.setattr("beddel_auth_github.provider.CREDENTIALS_PATH", creds)
        save_credentials(
            CredentialData(
                access_token="gho_abc123",
                github_user="testuser",
                server_url=None,
                created_at="2026-03-27T00:00:00Z",
            )
        )

        assert get_auth_headers() is None


class TestCheckTokenValidityValid:
    """check_token_validity returns True on HTTP 200."""

    @pytest.mark.asyncio
    async def test_check_token_validity_valid(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"login": "octocat"})

        monkeypatch.setattr(httpx, "AsyncClient", _mock_client(handler))

        assert await check_token_validity("gho_valid") is True


class TestCheckTokenValidityInvalid:
    """check_token_validity returns False on HTTP 401."""

    @pytest.mark.asyncio
    async def test_check_token_validity_invalid(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"message": "Bad credentials"})

        monkeypatch.setattr(httpx, "AsyncClient", _mock_client(handler))

        assert await check_token_validity("gho_expired") is False
