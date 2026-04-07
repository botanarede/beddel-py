"""Tests for the ``beddel connect`` CLI command."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
from beddel_auth_github.provider import CredentialData
from click.testing import CliRunner

from beddel.cli.commands import cli


def _sample_creds() -> CredentialData:
    return CredentialData(
        access_token="gho_abc123",
        github_user="testuser",
        server_url="https://dash.example.com",
        created_at="2026-03-27T00:00:00+00:00",
    )


class TestConnectDefaultClientId:
    """Default flow uses hardcoded client_id when env var is not set."""

    def test_connect_uses_default_client_id(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("BEDDEL_GITHUB_CLIENT_ID", raising=False)

        # Mock the device flow to capture the client_id used
        captured_client_ids: list[str] = []

        async def _mock_initiate(client_id: str) -> dict[str, Any]:
            captured_client_ids.append(client_id)
            return {
                "device_code": "dc_test",
                "user_code": "TEST-CODE",
                "verification_uri": "https://github.com/login/device",
                "expires_in": 900,
                "interval": 5,
            }

        monkeypatch.setattr(
            "beddel_auth_github.provider.initiate_device_flow",
            _mock_initiate,
        )
        monkeypatch.setattr(
            "beddel_auth_github.provider.poll_for_token",
            AsyncMock(return_value="gho_test"),
        )
        monkeypatch.setattr(
            "beddel_auth_github.provider.get_github_user",
            AsyncMock(return_value="testuser"),
        )
        monkeypatch.setattr(
            "beddel_auth_github.provider.save_credentials",
            lambda _d: None,
        )

        import unittest.mock

        mock_response = unittest.mock.MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"session_id": "s"}

        async def _mock_post(*_a: Any, **_k: Any) -> Any:
            return mock_response

        mock_client = unittest.mock.MagicMock()
        mock_client.post = _mock_post
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        monkeypatch.setattr("httpx.AsyncClient", lambda **_kw: mock_client)
        monkeypatch.setattr("webbrowser.open", lambda _url: True)

        runner = CliRunner()
        result = runner.invoke(cli, ["connect", "--url", "https://test.example.com"])
        assert result.exit_code == 0
        assert len(captured_client_ids) == 1
        assert captured_client_ids[0] == "Ov23lieA07aQzUjKcAHk"


class TestConnectStatusNoCredentials:
    """--status when no credentials exist."""

    def test_connect_status_no_credentials(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("beddel_auth_github.provider.load_credentials", lambda: None)
        runner = CliRunner()
        result = runner.invoke(cli, ["connect", "--status"])
        assert result.exit_code == 0
        assert "Not authenticated" in result.output


class TestConnectStatusWithCredentials:
    """--status when credentials exist."""

    def test_connect_status_with_credentials(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "beddel_auth_github.provider.load_credentials", lambda: _sample_creds()
        )
        runner = CliRunner()
        result = runner.invoke(cli, ["connect", "--status"])
        assert result.exit_code == 0
        assert "testuser" in result.output
        assert "dash.example.com" in result.output


class TestConnectLogout:
    """--logout when credentials exist."""

    def test_connect_logout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("beddel_auth_github.provider.delete_credentials", lambda: True)
        runner = CliRunner()
        result = runner.invoke(cli, ["connect", "--logout"])
        assert result.exit_code == 0
        assert "Credentials removed" in result.output


class TestConnectLogoutNoCredentials:
    """--logout when no credentials exist."""

    def test_connect_logout_no_credentials(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("beddel_auth_github.provider.delete_credentials", lambda: False)
        runner = CliRunner()
        result = runner.invoke(cli, ["connect", "--logout"])
        assert result.exit_code == 0
        assert "No credentials found" in result.output


class TestConnectServerUpdate:
    """--server updates server_url in existing credentials."""

    def test_connect_server_update(self, monkeypatch: pytest.MonkeyPatch) -> None:
        saved: list[CredentialData] = []
        creds = _sample_creds()
        creds["server_url"] = None

        monkeypatch.setattr("beddel_auth_github.provider.load_credentials", lambda: creds)
        monkeypatch.setattr(
            "beddel_auth_github.provider.save_credentials",
            lambda d: saved.append(d),
        )

        runner = CliRunner()
        result = runner.invoke(cli, ["connect", "--server", "https://new.example.com"])
        assert result.exit_code == 0
        assert "Server URL updated" in result.output
        assert saved[0]["server_url"] == "https://new.example.com"


class TestConnectServerNoCredentials:
    """--server when no credentials exist."""

    def test_connect_server_no_credentials(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("beddel_auth_github.provider.load_credentials", lambda: None)
        runner = CliRunner()
        result = runner.invoke(cli, ["connect", "--server", "https://x.com"])
        assert result.exit_code != 0
        assert "Not authenticated" in result.output


class TestConnectFullFlow:
    """Full Device Flow end-to-end (all GitHub API calls mocked)."""

    def test_connect_full_flow(self, monkeypatch: pytest.MonkeyPatch) -> None:
        flow_data: dict[str, Any] = {
            "device_code": "dc_test",
            "user_code": "ABCD-1234",
            "verification_uri": "https://github.com/login/device",
            "expires_in": 900,
            "interval": 5,
        }

        monkeypatch.setenv("BEDDEL_GITHUB_CLIENT_ID", "test-id")

        monkeypatch.setattr(
            "beddel_auth_github.provider.initiate_device_flow",
            AsyncMock(return_value=flow_data),
        )
        monkeypatch.setattr(
            "beddel_auth_github.provider.poll_for_token",
            AsyncMock(return_value="gho_tok_test"),
        )
        monkeypatch.setattr(
            "beddel_auth_github.provider.get_github_user",
            AsyncMock(return_value="octocat"),
        )

        saved: list[CredentialData] = []
        monkeypatch.setattr(
            "beddel_auth_github.provider.save_credentials",
            lambda d: saved.append(d),
        )

        # Mock httpx to prevent real network calls during token exchange
        import unittest.mock

        mock_response = unittest.mock.MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"session_id": "test-session-id"}

        async def _mock_post(*_args: Any, **_kwargs: Any) -> Any:
            return mock_response

        mock_client = unittest.mock.MagicMock()
        mock_client.post = _mock_post
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        monkeypatch.setattr("httpx.AsyncClient", lambda **_kw: mock_client)

        # Mock webbrowser.open to prevent browser launch
        monkeypatch.setattr("webbrowser.open", lambda _url: True)

        runner = CliRunner()
        result = runner.invoke(cli, ["connect", "--url", "https://test.example.com"])
        assert result.exit_code == 0
        assert "ABCD-1234" in result.output
        assert "Authenticated as octocat" in result.output
        assert len(saved) == 1
        assert saved[0]["access_token"] == "gho_tok_test"
        assert saved[0]["github_user"] == "octocat"
        assert saved[0]["server_url"] == "https://test.example.com"


class TestConnectNoUrl:
    """Default flow without --url prints error and exits."""

    def test_connect_no_url(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["connect"])
        assert result.exit_code == 1
        assert "Missing --url" in result.output


class TestConnectStatusNoServerUrl:
    """--status when credentials exist but server_url is None."""

    def test_connect_status_no_server_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        creds = _sample_creds()
        creds["server_url"] = None
        monkeypatch.setattr("beddel_auth_github.provider.load_credentials", lambda: creds)
        runner = CliRunner()
        result = runner.invoke(cli, ["connect", "--status"])
        assert result.exit_code == 0
        assert "(not configured)" in result.output


class TestConnectListenNoServerUrl:
    """--listen when server_url is not configured."""

    def test_connect_listen_no_server_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        creds = _sample_creds()
        creds["server_url"] = None
        monkeypatch.setattr("beddel_auth_github.provider.load_credentials", lambda: creds)
        runner = CliRunner()
        result = runner.invoke(cli, ["connect", "--listen"])
        assert result.exit_code == 1
        assert "Server URL not configured" in result.output


# ---------------------------------------------------------------------------
# Tests for ``beddel status`` command (Story 4.0A.4, Task 2)
# ---------------------------------------------------------------------------


class TestStatusNoCredentials:
    """``beddel status`` when no credentials exist."""

    def test_status_no_credentials(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("beddel_auth_github.provider.load_credentials", lambda: None)
        runner = CliRunner()
        result = runner.invoke(cli, ["status"])
        assert result.exit_code == 0
        assert "Not connected" in result.output


class TestStatusWithValidToken:
    """``beddel status`` with valid token."""

    def test_status_with_valid_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "beddel_auth_github.provider.load_credentials", lambda: _sample_creds()
        )
        monkeypatch.setattr(
            "beddel_auth_github.provider.check_token_validity",
            AsyncMock(return_value=True),
        )
        runner = CliRunner()
        result = runner.invoke(cli, ["status"])
        assert result.exit_code == 0
        assert "testuser" in result.output
        assert "dash.example.com" in result.output
        assert "Token: valid" in result.output


class TestStatusWithExpiredToken:
    """``beddel status`` with expired token."""

    def test_status_with_expired_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "beddel_auth_github.provider.load_credentials", lambda: _sample_creds()
        )
        monkeypatch.setattr(
            "beddel_auth_github.provider.check_token_validity",
            AsyncMock(return_value=False),
        )
        runner = CliRunner()
        result = runner.invoke(cli, ["status"])
        assert result.exit_code == 0
        assert "expired" in result.output
        assert "beddel connect" in result.output


class TestStatusNoServerUrl:
    """``beddel status`` when server_url is not configured."""

    def test_status_no_server_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        creds = _sample_creds()
        creds["server_url"] = None
        monkeypatch.setattr("beddel_auth_github.provider.load_credentials", lambda: creds)
        monkeypatch.setattr(
            "beddel_auth_github.provider.check_token_validity",
            AsyncMock(return_value=True),
        )
        runner = CliRunner()
        result = runner.invoke(cli, ["status"])
        assert result.exit_code == 0
        assert "(not configured)" in result.output
