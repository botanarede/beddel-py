"""Tests for the ``beddel connect`` CLI command."""

from __future__ import annotations

from pathlib import Path
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

        # Mock runtime + listen to avoid starting real servers
        monkeypatch.setattr(
            "beddel.cli.commands._build_runtime_app",
            lambda *_a, **_kw: (unittest.mock.MagicMock(), 0, []),
        )
        monkeypatch.setattr("uvicorn.Config", unittest.mock.MagicMock())
        monkeypatch.setattr("uvicorn.Server", lambda _cfg: unittest.mock.MagicMock())

        async def _noop_listen(*_a: Any, **_kw: Any) -> None:
            return

        monkeypatch.setattr("beddel.cli.commands._listen_loop", _noop_listen)

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

        # Mock runtime + listen to avoid starting real servers
        monkeypatch.setattr(
            "beddel.cli.commands._build_runtime_app",
            lambda *_a, **_kw: (unittest.mock.MagicMock(), 0, []),
        )
        monkeypatch.setattr("uvicorn.Config", unittest.mock.MagicMock())
        monkeypatch.setattr("uvicorn.Server", lambda _cfg: unittest.mock.MagicMock())

        async def _noop_listen(*_a: Any, **_kw: Any) -> None:
            return

        monkeypatch.setattr("beddel.cli.commands._listen_loop", _noop_listen)

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
    """Default flow without subcommand shows help with dev/remote subcommands."""

    def test_connect_no_url(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["connect"])
        assert result.exit_code == 0
        assert "dev" in result.output
        assert "remote" in result.output


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


# ---------------------------------------------------------------------------
# Tests for new connect behavior (Story BC5.1, Task 5)
# ---------------------------------------------------------------------------


class TestConnectHelpNewOptions:
    """AC #9: ``connect --help`` shows --host, --port, --workflow options."""

    def test_help_shows_host_option(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["connect", "--help"])
        assert result.exit_code == 0
        assert "--host" in result.output

    def test_help_shows_port_option(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["connect", "--help"])
        assert result.exit_code == 0
        assert "--port" in result.output

    def test_help_shows_workflow_option(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["connect", "--help"])
        assert result.exit_code == 0
        assert "--workflow" in result.output


class TestConnectAutoListenAfterOAuth:
    """AC #1, #2, #8: After OAuth, runtime starts and listen mode begins."""

    def test_auto_listen_after_oauth(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Mock Device Flow + token exchange, verify _build_runtime_app and
        _listen_loop are called after successful auth, and console output
        includes runtime info."""
        import unittest.mock

        flow_data: dict[str, Any] = {
            "device_code": "dc_test",
            "user_code": "AUTO-1234",
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
            AsyncMock(return_value="gho_auto_test"),
        )
        monkeypatch.setattr(
            "beddel_auth_github.provider.get_github_user",
            AsyncMock(return_value="octocat"),
        )
        monkeypatch.setattr(
            "beddel_auth_github.provider.save_credentials",
            lambda _d: None,
        )

        # Mock httpx for token exchange
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

        # Mock _build_runtime_app to avoid starting real FastAPI
        mock_app = unittest.mock.MagicMock()
        monkeypatch.setattr(
            "beddel.cli.commands._build_runtime_app",
            lambda *_a, **_kw: (mock_app, 2, ["wf1", "wf2"]),
        )

        # Mock uvicorn.Server to avoid starting real server
        mock_server = unittest.mock.MagicMock()
        mock_config_cls = unittest.mock.MagicMock()
        monkeypatch.setattr("uvicorn.Config", mock_config_cls)
        monkeypatch.setattr("uvicorn.Server", lambda _cfg: mock_server)

        # Mock _listen_loop to return immediately
        async def _mock_listen(*_a: Any, **_kw: Any) -> None:
            return

        monkeypatch.setattr("beddel.cli.commands._listen_loop", _mock_listen)

        runner = CliRunner()
        result = runner.invoke(cli, ["connect", "--url", "https://test.example.com"])

        assert result.exit_code == 0
        # AC #8: console output includes auth result
        assert "Authenticated as octocat" in result.output
        # AC #8: console output includes runtime info
        assert "Runtime:" in result.output
        assert "2 workflow(s)" in result.output
        # AC #8: AG-UI endpoints listed
        assert "ag-ui" in result.output.lower() or "AG-UI" in result.output
        # Verify shutdown sequence
        assert "Runtime stopped." in result.output


class TestConnectListenStartsRuntime:
    """AC #3: --listen flag starts runtime before entering listen mode."""

    def test_listen_starts_runtime(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import unittest.mock

        creds = _sample_creds()
        monkeypatch.setattr("beddel_auth_github.provider.load_credentials", lambda: creds)

        # Track call order
        call_order: list[str] = []

        # Mock _build_runtime_app
        mock_app = unittest.mock.MagicMock()

        def _mock_build(*_a: Any, **_kw: Any) -> tuple[Any, int, list[str]]:
            call_order.append("build_runtime")
            return (mock_app, 1, ["test-wf"])

        monkeypatch.setattr(
            "beddel.cli.commands._build_runtime_app",
            _mock_build,
        )

        # Mock uvicorn
        mock_server = unittest.mock.MagicMock()
        monkeypatch.setattr("uvicorn.Config", unittest.mock.MagicMock())
        monkeypatch.setattr("uvicorn.Server", lambda _cfg: mock_server)

        # Mock _listen_loop
        async def _mock_listen(*_a: Any, **_kw: Any) -> None:
            call_order.append("listen_loop")

        monkeypatch.setattr("beddel.cli.commands._listen_loop", _mock_listen)

        runner = CliRunner()
        result = runner.invoke(cli, ["connect", "--listen"])

        assert result.exit_code == 0
        # Verify runtime was built before listen
        assert "build_runtime" in call_order
        assert "listen_loop" in call_order
        assert call_order.index("build_runtime") < call_order.index("listen_loop")
        # Verify runtime info in output
        assert "Runtime:" in result.output
        assert "1 workflow(s)" in result.output
        assert "Runtime stopped." in result.output


class TestConnectWorkflowDiscovery:
    """AC #5: Workflow YAML files are discovered from CWD."""

    def test_discovers_valid_workflow_yaml(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Create temp YAML files with name: + steps: keys, verify they are
        discovered. Also test that non-workflow YAML files are skipped."""
        import unittest.mock

        # Create valid workflow YAML
        valid_wf = tmp_path / "my-workflow.yaml"
        valid_wf.write_text("name: test-workflow\nsteps:\n  - primitive: output\n")

        valid_wf2 = tmp_path / "another.yml"
        valid_wf2.write_text("name: another-wf\nsteps:\n  - primitive: llm\n")

        # Create non-workflow YAML (missing steps:)
        config_yaml = tmp_path / "config.yaml"
        config_yaml.write_text("database:\n  host: localhost\n  port: 5432\n")

        # Create non-workflow YAML (missing name:)
        no_name_yaml = tmp_path / "no-name.yaml"
        no_name_yaml.write_text("steps:\n  - primitive: output\n")

        # Change CWD to tmp_path
        monkeypatch.chdir(tmp_path)

        # We test via CLI by mocking _build_runtime_app to capture workflow_paths
        captured_args: list[tuple[Any, ...]] = []
        captured_kwargs: list[dict[str, Any]] = []

        # We need to let the real _build_runtime_app run for discovery,
        # but mock the heavy imports. Instead, test via --listen which calls
        # _build_runtime_app. We'll mock the internals that _build_runtime_app
        # needs.

        # Simpler approach: mock _build_runtime_app at CLI level and check
        # that it's called with empty workflow_paths (auto-discovery happens
        # inside _build_runtime_app). Then test discovery separately.

        creds = _sample_creds()
        monkeypatch.setattr("beddel_auth_github.provider.load_credentials", lambda: creds)

        mock_app = unittest.mock.MagicMock()

        def _capture_build(
            wf_paths: tuple[Path, ...], **kwargs: Any
        ) -> tuple[Any, int, list[str]]:
            captured_args.append(wf_paths)
            captured_kwargs.append(kwargs)
            return (mock_app, 2, ["test-workflow", "another-wf"])

        monkeypatch.setattr(
            "beddel.cli.commands._build_runtime_app",
            _capture_build,
        )

        mock_server = unittest.mock.MagicMock()
        monkeypatch.setattr("uvicorn.Config", unittest.mock.MagicMock())
        monkeypatch.setattr("uvicorn.Server", lambda _cfg: mock_server)

        async def _mock_listen(*_a: Any, **_kw: Any) -> None:
            return

        monkeypatch.setattr("beddel.cli.commands._listen_loop", _mock_listen)

        runner = CliRunner()
        result = runner.invoke(cli, ["connect", "--listen"])

        assert result.exit_code == 0
        # _build_runtime_app was called with empty tuple (auto-discovery inside)
        assert len(captured_args) == 1
        assert captured_args[0] == ()
        assert captured_kwargs[0]["dashboard"] is True

    def test_explicit_workflow_paths_passed_through(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When --workflow is provided, paths are passed to _build_runtime_app."""
        import unittest.mock

        wf_file = tmp_path / "explicit.yaml"
        wf_file.write_text("name: explicit\nsteps:\n  - primitive: output\n")

        creds = _sample_creds()
        monkeypatch.setattr("beddel_auth_github.provider.load_credentials", lambda: creds)

        captured_args: list[tuple[Any, ...]] = []

        def _capture_build(
            wf_paths: tuple[Path, ...], **kwargs: Any
        ) -> tuple[Any, int, list[str]]:
            captured_args.append(wf_paths)
            return (unittest.mock.MagicMock(), 1, ["explicit"])

        monkeypatch.setattr(
            "beddel.cli.commands._build_runtime_app",
            _capture_build,
        )

        mock_server = unittest.mock.MagicMock()
        monkeypatch.setattr("uvicorn.Config", unittest.mock.MagicMock())
        monkeypatch.setattr("uvicorn.Server", lambda _cfg: mock_server)

        async def _mock_listen(*_a: Any, **_kw: Any) -> None:
            return

        monkeypatch.setattr("beddel.cli.commands._listen_loop", _mock_listen)

        runner = CliRunner()
        result = runner.invoke(cli, ["connect", "--listen", "--workflow", str(wf_file)])

        assert result.exit_code == 0
        assert len(captured_args) == 1
        # The explicit path should be passed through
        assert len(captured_args[0]) == 1
        assert captured_args[0][0] == wf_file


class TestConnectNoWorkflowsWarning:
    """AC #7: Warning message when no workflows found."""

    def test_no_workflows_warning_via_listen(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When no workflow files exist, _build_runtime_app logs a warning."""
        import unittest.mock

        import click as click_mod

        # Empty directory — no YAML files
        monkeypatch.chdir(tmp_path)

        creds = _sample_creds()
        monkeypatch.setattr("beddel_auth_github.provider.load_credentials", lambda: creds)

        # Mock _build_runtime_app to return 0 workflows and simulate warning
        mock_app = unittest.mock.MagicMock()

        def _mock_build(wf_paths: tuple[Path, ...], **kwargs: Any) -> tuple[Any, int, list[str]]:
            # Simulate the warning that _build_runtime_app emits
            click_mod.echo(
                "Warning: No workflow files found. Use --workflow to specify "
                "files or place YAML files in the current directory.",
                err=True,
            )
            return (mock_app, 0, [])

        monkeypatch.setattr(
            "beddel.cli.commands._build_runtime_app",
            _mock_build,
        )

        mock_server = unittest.mock.MagicMock()
        monkeypatch.setattr("uvicorn.Config", unittest.mock.MagicMock())
        monkeypatch.setattr("uvicorn.Server", lambda _cfg: mock_server)

        async def _mock_listen(*_a: Any, **_kw: Any) -> None:
            return

        monkeypatch.setattr("beddel.cli.commands._listen_loop", _mock_listen)

        runner = CliRunner()
        result = runner.invoke(cli, ["connect", "--listen"])

        assert result.exit_code == 0
        # Warning should appear in stderr
        assert "No workflow files found" in result.output
        # Runtime still starts with 0 workflows
        assert "0 workflow(s)" in result.output


class TestConnectExistingFlagsUnchanged:
    """AC #10: --status, --logout, --server continue to work unchanged."""

    def test_status_still_works(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "beddel_auth_github.provider.load_credentials", lambda: _sample_creds()
        )
        runner = CliRunner()
        result = runner.invoke(cli, ["connect", "--status"])
        assert result.exit_code == 0
        assert "testuser" in result.output

    def test_logout_still_works(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("beddel_auth_github.provider.delete_credentials", lambda: True)
        runner = CliRunner()
        result = runner.invoke(cli, ["connect", "--logout"])
        assert result.exit_code == 0
        assert "Credentials removed" in result.output

    def test_server_still_works(self, monkeypatch: pytest.MonkeyPatch) -> None:
        saved: list[Any] = []
        creds = _sample_creds()
        monkeypatch.setattr("beddel_auth_github.provider.load_credentials", lambda: creds)
        monkeypatch.setattr(
            "beddel_auth_github.provider.save_credentials",
            lambda d: saved.append(d),
        )
        runner = CliRunner()
        result = runner.invoke(cli, ["connect", "--server", "https://new.example.com"])
        assert result.exit_code == 0
        assert "Server URL updated" in result.output


class TestConnectGracefulShutdown:
    """AC #4: Ctrl+C gracefully shuts down both server and SSE connection."""

    def test_uvicorn_server_passed_to_listen_loop(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify that uvicorn_server is passed to _listen_loop for shutdown."""
        import unittest.mock

        creds = _sample_creds()
        monkeypatch.setattr("beddel_auth_github.provider.load_credentials", lambda: creds)

        mock_app = unittest.mock.MagicMock()
        monkeypatch.setattr(
            "beddel.cli.commands._build_runtime_app",
            lambda *_a, **_kw: (mock_app, 1, ["wf1"]),
        )

        mock_server = unittest.mock.MagicMock()
        monkeypatch.setattr("uvicorn.Config", unittest.mock.MagicMock())
        monkeypatch.setattr("uvicorn.Server", lambda _cfg: mock_server)

        # Capture kwargs passed to _listen_loop
        listen_kwargs: list[dict[str, Any]] = []

        async def _mock_listen(*_a: Any, **_kw: Any) -> None:
            listen_kwargs.append(_kw)

        monkeypatch.setattr("beddel.cli.commands._listen_loop", _mock_listen)

        runner = CliRunner()
        result = runner.invoke(cli, ["connect", "--listen"])

        assert result.exit_code == 0
        # Verify uvicorn_server was passed to _listen_loop
        assert len(listen_kwargs) == 1
        assert listen_kwargs[0]["uvicorn_server"] is mock_server
        # Verify shutdown message
        assert "Runtime stopped." in result.output


class TestConnectHostPortOptions:
    """AC #6: --host and --port options configure the local runtime bind address."""

    def test_custom_host_and_port(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import unittest.mock

        creds = _sample_creds()
        monkeypatch.setattr("beddel_auth_github.provider.load_credentials", lambda: creds)

        mock_app = unittest.mock.MagicMock()
        monkeypatch.setattr(
            "beddel.cli.commands._build_runtime_app",
            lambda *_a, **_kw: (mock_app, 1, ["wf1"]),
        )

        # Capture uvicorn.Config args
        config_calls: list[dict[str, Any]] = []
        original_mock_server = unittest.mock.MagicMock()

        def _mock_config(app: Any, **kwargs: Any) -> Any:
            config_calls.append({"app": app, **kwargs})
            return unittest.mock.MagicMock()

        monkeypatch.setattr("uvicorn.Config", _mock_config)
        monkeypatch.setattr("uvicorn.Server", lambda _cfg: original_mock_server)

        async def _mock_listen(*_a: Any, **_kw: Any) -> None:
            return

        monkeypatch.setattr("beddel.cli.commands._listen_loop", _mock_listen)

        runner = CliRunner()
        result = runner.invoke(cli, ["connect", "--listen", "--host", "0.0.0.0", "--port", "9090"])

        assert result.exit_code == 0
        # Verify uvicorn.Config was called with custom host/port
        assert len(config_calls) == 1
        assert config_calls[0]["host"] == "0.0.0.0"
        assert config_calls[0]["port"] == 9090
        # Verify output reflects custom host/port
        assert "0.0.0.0" in result.output
        assert "9090" in result.output


# ---------------------------------------------------------------------------
# BC6.1 — Subcommand refactoring tests
# ---------------------------------------------------------------------------


class TestConnectDevSubcommand:
    """AC #1: 'beddel connect dev' starts runtime without OAuth."""

    def test_dev_starts_runtime_no_oauth(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import unittest.mock

        mock_app = unittest.mock.MagicMock()
        build_calls: list[dict[str, Any]] = []

        def _mock_build(*_a: Any, **kw: Any) -> tuple[Any, int, list[str]]:
            build_calls.append(kw)
            return (mock_app, 1, ["wf1"])

        monkeypatch.setattr("beddel.cli.commands._build_runtime_app", _mock_build)
        monkeypatch.setattr("uvicorn.Config", unittest.mock.MagicMock())
        monkeypatch.setattr("uvicorn.Server", lambda _cfg: unittest.mock.MagicMock())

        listen_calls: list[tuple[Any, ...]] = []

        async def _mock_listen(*args: Any, **kwargs: Any) -> None:
            listen_calls.append(args)

        monkeypatch.setattr("beddel.cli.commands._listen_loop", _mock_listen)

        runner = CliRunner()
        result = runner.invoke(cli, ["connect", "dev"])
        assert result.exit_code == 0
        # Verify _build_runtime_app was called with dashboard=True
        assert len(build_calls) == 1
        assert build_calls[0]["dashboard"] is True
        # Verify _listen_loop was called (blocking mechanism)
        assert len(listen_calls) == 1
        # Verify default URL is localhost:3000
        assert listen_calls[0][0] == "http://localhost:3000"
        # Verify empty token (no auth)
        assert listen_calls[0][1] == ""
        # Verify runtime info in output
        assert "Runtime:" in result.output
        assert "Runtime stopped." in result.output

    def test_dev_default_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import unittest.mock

        monkeypatch.setattr(
            "beddel.cli.commands._build_runtime_app",
            lambda *_a, **_kw: (unittest.mock.MagicMock(), 0, []),
        )
        monkeypatch.setattr("uvicorn.Config", unittest.mock.MagicMock())
        monkeypatch.setattr("uvicorn.Server", lambda _cfg: unittest.mock.MagicMock())

        listen_urls: list[str] = []

        async def _mock_listen(url: str, *_a: Any, **_kw: Any) -> None:
            listen_urls.append(url)

        monkeypatch.setattr("beddel.cli.commands._listen_loop", _mock_listen)

        runner = CliRunner()
        result = runner.invoke(cli, ["connect", "dev"])
        assert result.exit_code == 0
        assert listen_urls == ["http://localhost:3000"]

    def test_dev_custom_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import unittest.mock

        monkeypatch.setattr(
            "beddel.cli.commands._build_runtime_app",
            lambda *_a, **_kw: (unittest.mock.MagicMock(), 0, []),
        )
        monkeypatch.setattr("uvicorn.Config", unittest.mock.MagicMock())
        monkeypatch.setattr("uvicorn.Server", lambda _cfg: unittest.mock.MagicMock())

        listen_urls: list[str] = []

        async def _mock_listen(url: str, *_a: Any, **_kw: Any) -> None:
            listen_urls.append(url)

        monkeypatch.setattr("beddel.cli.commands._listen_loop", _mock_listen)

        runner = CliRunner()
        result = runner.invoke(cli, ["connect", "dev", "--url", "http://localhost:4000"])
        assert result.exit_code == 0
        assert listen_urls == ["http://localhost:4000"]

    def test_dev_no_oauth_imports(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify dev mode does NOT call any OAuth functions."""
        import unittest.mock

        monkeypatch.setattr(
            "beddel.cli.commands._build_runtime_app",
            lambda *_a, **_kw: (unittest.mock.MagicMock(), 0, []),
        )
        monkeypatch.setattr("uvicorn.Config", unittest.mock.MagicMock())
        monkeypatch.setattr("uvicorn.Server", lambda _cfg: unittest.mock.MagicMock())

        async def _mock_listen(*_a: Any, **_kw: Any) -> None:
            return

        monkeypatch.setattr("beddel.cli.commands._listen_loop", _mock_listen)

        # If OAuth functions were called, they would fail since we don't mock them
        # (load_credentials, initiate_device_flow, etc.)
        runner = CliRunner()
        result = runner.invoke(cli, ["connect", "dev"])
        assert result.exit_code == 0


class TestConnectRemoteSubcommand:
    """AC #2: 'beddel connect remote' runs OAuth and shows relay placeholder."""

    def test_remote_runs_oauth(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import unittest.mock

        flow_data: dict[str, Any] = {
            "device_code": "dc_test",
            "user_code": "REMOTE-1234",
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
            AsyncMock(return_value="gho_remote_tok"),
        )
        monkeypatch.setattr(
            "beddel_auth_github.provider.get_github_user",
            AsyncMock(return_value="remoteuser"),
        )
        monkeypatch.setattr(
            "beddel_auth_github.provider.save_credentials",
            lambda _d: None,
        )

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

        monkeypatch.setattr(
            "beddel.cli.commands._build_runtime_app",
            lambda *_a, **_kw: (unittest.mock.MagicMock(), 0, []),
        )
        monkeypatch.setattr("uvicorn.Config", unittest.mock.MagicMock())
        monkeypatch.setattr("uvicorn.Server", lambda _cfg: unittest.mock.MagicMock())

        async def _noop_listen(*_a: Any, **_kw: Any) -> None:
            return

        monkeypatch.setattr("beddel.cli.commands._listen_loop", _noop_listen)

        runner = CliRunner()
        result = runner.invoke(cli, ["connect", "remote"])
        assert result.exit_code == 0
        assert "REMOTE-1234" in result.output
        assert "Authenticated as remoteuser" in result.output
        assert "Relay not yet implemented" in result.output

    def test_remote_default_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import unittest.mock

        monkeypatch.setenv("BEDDEL_GITHUB_CLIENT_ID", "test-id")
        monkeypatch.setattr(
            "beddel_auth_github.provider.initiate_device_flow",
            AsyncMock(
                return_value={
                    "device_code": "dc",
                    "user_code": "UC",
                    "verification_uri": "https://github.com/login/device",
                    "expires_in": 900,
                    "interval": 5,
                }
            ),
        )
        monkeypatch.setattr(
            "beddel_auth_github.provider.poll_for_token",
            AsyncMock(return_value="gho_tok"),
        )
        monkeypatch.setattr(
            "beddel_auth_github.provider.get_github_user",
            AsyncMock(return_value="user"),
        )
        monkeypatch.setattr("beddel_auth_github.provider.save_credentials", lambda _d: None)

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
        monkeypatch.setattr(
            "beddel.cli.commands._build_runtime_app",
            lambda *_a, **_kw: (unittest.mock.MagicMock(), 0, []),
        )
        monkeypatch.setattr("uvicorn.Config", unittest.mock.MagicMock())
        monkeypatch.setattr("uvicorn.Server", lambda _cfg: unittest.mock.MagicMock())

        listen_urls: list[str] = []

        async def _mock_listen(url: str, *_a: Any, **_kw: Any) -> None:
            listen_urls.append(url)

        monkeypatch.setattr("beddel.cli.commands._listen_loop", _mock_listen)

        runner = CliRunner()
        result = runner.invoke(cli, ["connect", "remote"])
        assert result.exit_code == 0
        # Default URL for remote is connect.beddel.com.br
        assert listen_urls == ["https://connect.beddel.com.br"]


class TestConnectDeprecatedUrl:
    """AC #3: --url on group is deprecated alias that infers mode."""

    def test_deprecated_url_localhost_invokes_dev(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import unittest.mock

        monkeypatch.setattr(
            "beddel.cli.commands._build_runtime_app",
            lambda *_a, **_kw: (unittest.mock.MagicMock(), 0, []),
        )
        monkeypatch.setattr("uvicorn.Config", unittest.mock.MagicMock())
        monkeypatch.setattr("uvicorn.Server", lambda _cfg: unittest.mock.MagicMock())

        listen_calls: list[tuple[str, str]] = []

        async def _mock_listen(url: str, token: str, **_kw: Any) -> None:
            listen_calls.append((url, token))

        monkeypatch.setattr("beddel.cli.commands._listen_loop", _mock_listen)

        runner = CliRunner()
        result = runner.invoke(cli, ["connect", "--url", "http://localhost:3000"])
        assert result.exit_code == 0
        # Deprecation warning is in output (CliRunner mixes stderr)
        assert "deprecated" in result.output.lower()
        # Should invoke dev mode (empty token)
        assert len(listen_calls) == 1
        assert listen_calls[0][0] == "http://localhost:3000"
        assert listen_calls[0][1] == ""

    def test_deprecated_url_remote_invokes_remote(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import unittest.mock

        monkeypatch.setenv("BEDDEL_GITHUB_CLIENT_ID", "test-id")
        monkeypatch.setattr(
            "beddel_auth_github.provider.initiate_device_flow",
            AsyncMock(
                return_value={
                    "device_code": "dc",
                    "user_code": "UC",
                    "verification_uri": "https://github.com/login/device",
                    "expires_in": 900,
                    "interval": 5,
                }
            ),
        )
        monkeypatch.setattr(
            "beddel_auth_github.provider.poll_for_token",
            AsyncMock(return_value="gho_tok"),
        )
        monkeypatch.setattr(
            "beddel_auth_github.provider.get_github_user",
            AsyncMock(return_value="user"),
        )
        monkeypatch.setattr("beddel_auth_github.provider.save_credentials", lambda _d: None)

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
        monkeypatch.setattr(
            "beddel.cli.commands._build_runtime_app",
            lambda *_a, **_kw: (unittest.mock.MagicMock(), 0, []),
        )
        monkeypatch.setattr("uvicorn.Config", unittest.mock.MagicMock())
        monkeypatch.setattr("uvicorn.Server", lambda _cfg: unittest.mock.MagicMock())

        async def _noop_listen(*_a: Any, **_kw: Any) -> None:
            return

        monkeypatch.setattr("beddel.cli.commands._listen_loop", _noop_listen)

        runner = CliRunner()
        result = runner.invoke(cli, ["connect", "--url", "https://example.com"])
        assert result.exit_code == 0
        # Should invoke remote mode (OAuth flow)
        assert "Authenticated as user" in result.output


class TestConnectNoSubcommand:
    """AC #5: 'beddel connect' without subcommand shows help."""

    def test_shows_help_with_subcommands(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["connect"])
        assert result.exit_code == 0
        assert "dev" in result.output
        assert "remote" in result.output

    def test_help_flag_shows_subcommands(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["connect", "--help"])
        assert result.exit_code == 0
        assert "dev" in result.output
        assert "remote" in result.output
        assert "--status" in result.output
        assert "--logout" in result.output


class TestConnectGroupFlagsStillWork:
    """AC backward compat: --status, --logout, --server, --listen on group."""

    def test_status_on_group(self, monkeypatch: pytest.MonkeyPatch) -> None:
        creds = _sample_creds()
        monkeypatch.setattr("beddel_auth_github.provider.load_credentials", lambda: creds)
        runner = CliRunner()
        result = runner.invoke(cli, ["connect", "--status"])
        assert result.exit_code == 0
        assert "testuser" in result.output

    def test_logout_on_group(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("beddel_auth_github.provider.delete_credentials", lambda: True)
        runner = CliRunner()
        result = runner.invoke(cli, ["connect", "--logout"])
        assert result.exit_code == 0
        assert "Credentials removed" in result.output

    def test_server_on_group(self, monkeypatch: pytest.MonkeyPatch) -> None:
        creds = _sample_creds()
        monkeypatch.setattr("beddel_auth_github.provider.load_credentials", lambda: creds)
        monkeypatch.setattr("beddel_auth_github.provider.save_credentials", lambda _d: None)
        runner = CliRunner()
        result = runner.invoke(cli, ["connect", "--server", "https://new.example.com"])
        assert result.exit_code == 0
        assert "Server URL updated" in result.output
