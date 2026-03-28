"""Tests for the ``beddel connect`` CLI command."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
from click.testing import CliRunner

from beddel.adapters.github_auth import CredentialData
from beddel.cli.commands import cli


def _sample_creds() -> CredentialData:
    return CredentialData(
        access_token="gho_abc123",
        github_user="testuser",
        server_url="https://dash.example.com",
        created_at="2026-03-27T00:00:00+00:00",
    )


class TestConnectNoClientId:
    """Default flow without BEDDEL_GITHUB_CLIENT_ID set."""

    def test_connect_no_client_id(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("BEDDEL_GITHUB_CLIENT_ID", raising=False)
        runner = CliRunner()
        result = runner.invoke(cli, ["connect"])
        assert result.exit_code != 0
        assert "BEDDEL_GITHUB_CLIENT_ID" in result.output


class TestConnectStatusNoCredentials:
    """--status when no credentials exist."""

    def test_connect_status_no_credentials(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("beddel.adapters.github_auth.load_credentials", lambda: None)
        runner = CliRunner()
        result = runner.invoke(cli, ["connect", "--status"])
        assert result.exit_code == 0
        assert "Not authenticated" in result.output


class TestConnectStatusWithCredentials:
    """--status when credentials exist."""

    def test_connect_status_with_credentials(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "beddel.adapters.github_auth.load_credentials", lambda: _sample_creds()
        )
        runner = CliRunner()
        result = runner.invoke(cli, ["connect", "--status"])
        assert result.exit_code == 0
        assert "testuser" in result.output
        assert "dash.example.com" in result.output


class TestConnectLogout:
    """--logout when credentials exist."""

    def test_connect_logout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("beddel.adapters.github_auth.delete_credentials", lambda: True)
        runner = CliRunner()
        result = runner.invoke(cli, ["connect", "--logout"])
        assert result.exit_code == 0
        assert "Credentials removed" in result.output


class TestConnectLogoutNoCredentials:
    """--logout when no credentials exist."""

    def test_connect_logout_no_credentials(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("beddel.adapters.github_auth.delete_credentials", lambda: False)
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

        monkeypatch.setattr("beddel.adapters.github_auth.load_credentials", lambda: creds)
        monkeypatch.setattr(
            "beddel.adapters.github_auth.save_credentials",
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
        monkeypatch.setattr("beddel.adapters.github_auth.load_credentials", lambda: None)
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
            "beddel.adapters.github_auth.initiate_device_flow",
            AsyncMock(return_value=flow_data),
        )
        monkeypatch.setattr(
            "beddel.adapters.github_auth.poll_for_token",
            AsyncMock(return_value="gho_tok_test"),
        )
        monkeypatch.setattr(
            "beddel.adapters.github_auth.get_github_user",
            AsyncMock(return_value="octocat"),
        )

        saved: list[CredentialData] = []
        monkeypatch.setattr(
            "beddel.adapters.github_auth.save_credentials",
            lambda d: saved.append(d),
        )

        runner = CliRunner()
        result = runner.invoke(cli, ["connect"])
        assert result.exit_code == 0
        assert "ABCD-1234" in result.output
        assert "Authenticated as octocat" in result.output
        assert len(saved) == 1
        assert saved[0]["access_token"] == "gho_tok_test"
        assert saved[0]["github_user"] == "octocat"


# ---------------------------------------------------------------------------
# Tests for ``beddel serve`` remote options (Story 4.0A.2, Task 3)
# ---------------------------------------------------------------------------


class TestServeHelpShowsRemoteOptions:
    """``beddel serve --help`` includes --remote, --allowed-users, --tunnel-domain."""

    def test_serve_help_shows_remote_options(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["serve", "--help"])
        assert result.exit_code == 0
        assert "--remote" in result.output
        assert "--allowed-users" in result.output
        assert "--tunnel-domain" in result.output


class TestServeRemoteFlagAccepted:
    """``--remote`` flag is accepted without error (uvicorn mocked)."""

    def test_serve_remote_flag_accepted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("uvicorn.run", lambda *a, **kw: None)
        runner = CliRunner()
        result = runner.invoke(cli, ["serve", "--remote"])
        assert result.exit_code == 0
        assert "Remote mode enabled" in result.output
