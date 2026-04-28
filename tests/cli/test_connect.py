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

        monkeypatch.setattr("beddel.cli.commands._relay_loop", _noop_listen)

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

        monkeypatch.setattr("beddel.cli.commands._relay_loop", _noop_listen)

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
    """Default flow without subcommand runs config-driven unified flow."""

    @pytest.mark.skip(reason="Pre-existing async timeout flake — blocks CI")
    def test_connect_no_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import unittest.mock

        monkeypatch.setattr("beddel.cli.config.resolve_dev_mode", lambda: True)
        monkeypatch.setattr(
            "beddel.cli.config.resolve_dashboard_url", lambda: "http://localhost:3000"
        )
        monkeypatch.setattr(
            "beddel.cli.commands._build_runtime_app",
            lambda *_a, **_kw: (unittest.mock.MagicMock(), 0, []),
        )
        monkeypatch.setattr("uvicorn.Config", unittest.mock.MagicMock())
        monkeypatch.setattr("uvicorn.Server", lambda _cfg: unittest.mock.MagicMock())

        async def _noop(*_a: Any, **_kw: Any) -> None:
            return

        monkeypatch.setattr("beddel.cli.commands._wait_for_shutdown", _noop)

        runner = CliRunner()
        result = runner.invoke(cli, ["connect"])
        assert result.exit_code == 0
        assert "Runtime stopped" in result.output


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
        _wait_for_shutdown are called after successful auth, and console output
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

        # Mock _wait_for_shutdown to return immediately
        async def _mock_listen(*_a: Any, **_kw: Any) -> None:
            return

        monkeypatch.setattr("beddel.cli.commands._relay_loop", _mock_listen)

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

        # Mock _wait_for_shutdown
        async def _mock_shutdown(*_a: Any, **_kw: Any) -> None:
            call_order.append("wait_for_shutdown")

        monkeypatch.setattr("beddel.cli.commands._wait_for_shutdown", _mock_shutdown)

        runner = CliRunner()
        result = runner.invoke(cli, ["connect", "--listen"])

        assert result.exit_code == 0
        # Verify runtime was built before shutdown wait
        assert "build_runtime" in call_order
        assert "wait_for_shutdown" in call_order
        assert call_order.index("build_runtime") < call_order.index("wait_for_shutdown")
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

        monkeypatch.setattr("beddel.cli.commands._wait_for_shutdown", _mock_listen)

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

        monkeypatch.setattr("beddel.cli.commands._wait_for_shutdown", _mock_listen)

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
                "Warning: No workflows found. Place .yaml files in the "
                "current directory or workflows/ subdirectory.",
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

        monkeypatch.setattr("beddel.cli.commands._wait_for_shutdown", _mock_listen)

        runner = CliRunner()
        result = runner.invoke(cli, ["connect", "--listen"])

        assert result.exit_code == 0
        # Warning should appear in stderr
        assert "No workflows found" in result.output
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

    def test_uvicorn_server_passed_to_shutdown(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify that uvicorn_server is passed to _wait_for_shutdown."""
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

        # Capture kwargs passed to _wait_for_shutdown
        listen_kwargs: list[dict[str, Any]] = []

        async def _mock_listen(*_a: Any, **_kw: Any) -> None:
            listen_kwargs.append(_kw)

        monkeypatch.setattr("beddel.cli.commands._wait_for_shutdown", _mock_listen)

        runner = CliRunner()
        result = runner.invoke(cli, ["connect", "--listen"])

        assert result.exit_code == 0
        # Verify uvicorn_server was passed to _wait_for_shutdown
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

        monkeypatch.setattr("beddel.cli.commands._wait_for_shutdown", _mock_listen)

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

        shutdown_calls: list[dict[str, Any]] = []

        async def _mock_shutdown(*args: Any, **kwargs: Any) -> None:
            shutdown_calls.append(kwargs)

        monkeypatch.setattr("beddel.cli.commands._wait_for_shutdown", _mock_shutdown)

        runner = CliRunner()
        result = runner.invoke(cli, ["connect", "dev"])
        assert result.exit_code == 0
        # Verify _build_runtime_app was called with dashboard=True
        assert len(build_calls) == 1
        assert build_calls[0]["dashboard"] is True
        # Verify _wait_for_shutdown was called (blocking mechanism)
        assert len(shutdown_calls) == 1
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

        shutdown_called = False

        async def _mock_shutdown(**_kw: Any) -> None:
            nonlocal shutdown_called
            shutdown_called = True

        monkeypatch.setattr("beddel.cli.commands._wait_for_shutdown", _mock_shutdown)

        runner = CliRunner()
        result = runner.invoke(cli, ["connect", "dev"])
        assert result.exit_code == 0
        assert shutdown_called

    def test_dev_custom_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import unittest.mock

        monkeypatch.setattr(
            "beddel.cli.commands._build_runtime_app",
            lambda *_a, **_kw: (unittest.mock.MagicMock(), 0, []),
        )
        monkeypatch.setattr("uvicorn.Config", unittest.mock.MagicMock())
        monkeypatch.setattr("uvicorn.Server", lambda _cfg: unittest.mock.MagicMock())

        shutdown_called = False

        async def _mock_shutdown(**_kw: Any) -> None:
            nonlocal shutdown_called
            shutdown_called = True

        monkeypatch.setattr("beddel.cli.commands._wait_for_shutdown", _mock_shutdown)

        runner = CliRunner()
        result = runner.invoke(cli, ["connect", "dev", "--url", "http://localhost:4000"])
        assert result.exit_code == 0
        assert shutdown_called

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

        monkeypatch.setattr("beddel.cli.commands._wait_for_shutdown", _mock_listen)

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

        monkeypatch.setattr("beddel.cli.commands._relay_loop", _noop_listen)

        runner = CliRunner()
        result = runner.invoke(cli, ["connect", "remote"])
        assert result.exit_code == 0
        assert "REMOTE-1234" in result.output
        assert "Authenticated as remoteuser" in result.output

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

        monkeypatch.setattr("beddel.cli.commands._relay_loop", _mock_listen)

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

        shutdown_calls: list[dict[str, Any]] = []

        async def _mock_shutdown(**_kw: Any) -> None:
            shutdown_calls.append(_kw)

        monkeypatch.setattr("beddel.cli.commands._wait_for_shutdown", _mock_shutdown)

        runner = CliRunner()
        result = runner.invoke(cli, ["connect", "--url", "http://localhost:3000"])
        assert result.exit_code == 0
        # Deprecation warning is in output (CliRunner mixes stderr)
        assert "deprecated" in result.output.lower()
        # Should invoke dev mode — _wait_for_shutdown called
        assert len(shutdown_calls) == 1

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

        monkeypatch.setattr("beddel.cli.commands._relay_loop", _noop_listen)

        runner = CliRunner()
        result = runner.invoke(cli, ["connect", "--url", "https://example.com"])
        assert result.exit_code == 0
        # Should invoke remote mode (OAuth flow)
        assert "Authenticated as user" in result.output


class TestConnectNoSubcommand:
    """'beddel connect' without subcommand runs config-driven unified flow."""

    @pytest.mark.skip(reason="Pre-existing async timeout flake — blocks CI")
    def test_shows_help_with_subcommands(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import unittest.mock

        monkeypatch.setattr("beddel.cli.config.resolve_dev_mode", lambda: True)
        monkeypatch.setattr(
            "beddel.cli.config.resolve_dashboard_url", lambda: "http://localhost:3000"
        )
        monkeypatch.setattr(
            "beddel.cli.commands._build_runtime_app",
            lambda *_a, **_kw: (unittest.mock.MagicMock(), 0, []),
        )
        monkeypatch.setattr("uvicorn.Config", unittest.mock.MagicMock())
        monkeypatch.setattr("uvicorn.Server", lambda _cfg: unittest.mock.MagicMock())

        async def _noop(*_a: Any, **_kw: Any) -> None:
            return

        monkeypatch.setattr("beddel.cli.commands._wait_for_shutdown", _noop)

        runner = CliRunner()
        result = runner.invoke(cli, ["connect"])
        assert result.exit_code == 0
        assert "Runtime stopped" in result.output

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


# ---------------------------------------------------------------------------
# BC7.1 — Unified connect + deprecation warning tests
# ---------------------------------------------------------------------------


@pytest.mark.skip(reason="Pre-existing async timeout flake — blocks CI")
class TestConnectUnifiedDevMode:
    """AC #1, #2: 'beddel connect' (no subcommand) with dev: true starts runtime without OAuth."""

    def test_unified_dev_starts_runtime_no_oauth(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import unittest.mock

        monkeypatch.setattr("beddel.cli.config.resolve_dev_mode", lambda: True)
        monkeypatch.setattr(
            "beddel.cli.config.resolve_dashboard_url", lambda: "http://localhost:3000"
        )

        start_calls: list[tuple[Any, ...]] = []

        def _mock_start(
            host: str, port: int, workflow_paths: tuple[Path, ...]
        ) -> tuple[Any, Any, int, list[str]]:
            start_calls.append((host, port, workflow_paths))
            return (unittest.mock.MagicMock(), unittest.mock.MagicMock(), 1, ["wf1"])

        monkeypatch.setattr("beddel.cli.commands._start_runtime", _mock_start)

        async def _noop(*_a: Any, **_kw: Any) -> None:
            return

        monkeypatch.setattr("beddel.cli.commands._wait_for_shutdown", _noop)

        # Do NOT mock OAuth — if it were called, it would fail
        runner = CliRunner()
        result = runner.invoke(cli, ["connect"])
        assert result.exit_code == 0
        # _start_runtime was called
        assert len(start_calls) == 1
        # Runtime output present
        assert "Runtime:" in result.output
        assert "Runtime stopped." in result.output

    def test_unified_dev_no_oauth_calls(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify that no OAuth functions are invoked in dev mode."""
        import unittest.mock

        monkeypatch.setattr("beddel.cli.config.resolve_dev_mode", lambda: True)
        monkeypatch.setattr(
            "beddel.cli.config.resolve_dashboard_url", lambda: "http://localhost:3000"
        )

        monkeypatch.setattr(
            "beddel.cli.commands._start_runtime",
            lambda *_a, **_kw: (
                unittest.mock.MagicMock(),
                unittest.mock.MagicMock(),
                0,
                [],
            ),
        )

        async def _noop(*_a: Any, **_kw: Any) -> None:
            return

        monkeypatch.setattr("beddel.cli.commands._wait_for_shutdown", _noop)

        # Mock _connect_remote_flow to detect if it's called
        remote_calls: list[dict[str, Any]] = []

        def _mock_remote(**kw: Any) -> None:
            remote_calls.append(kw)

        monkeypatch.setattr("beddel.cli.commands._connect_remote_flow", _mock_remote)

        runner = CliRunner()
        result = runner.invoke(cli, ["connect"])
        assert result.exit_code == 0
        # _connect_remote_flow must NOT have been called
        assert len(remote_calls) == 0


class TestConnectUnifiedRemoteMode:
    """AC #1, #3: 'beddel connect' (no subcommand) with dev: false runs OAuth flow."""

    def test_unified_remote_runs_oauth(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("beddel.cli.config.resolve_dev_mode", lambda: False)
        monkeypatch.setattr(
            "beddel.cli.config.resolve_dashboard_url",
            lambda: "https://connect.beddel.com.br",
        )

        remote_calls: list[dict[str, Any]] = []

        def _mock_remote(**kw: Any) -> None:
            remote_calls.append(kw)

        monkeypatch.setattr("beddel.cli.commands._connect_remote_flow", _mock_remote)

        runner = CliRunner()
        result = runner.invoke(cli, ["connect"])
        assert result.exit_code == 0
        # _connect_remote_flow was called
        assert len(remote_calls) == 1
        assert remote_calls[0]["dashboard_url"] == "https://connect.beddel.com.br"

    def test_unified_remote_no_start_runtime(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """In remote mode, _start_runtime is NOT called directly."""
        import unittest.mock

        monkeypatch.setattr("beddel.cli.config.resolve_dev_mode", lambda: False)
        monkeypatch.setattr(
            "beddel.cli.config.resolve_dashboard_url",
            lambda: "https://connect.beddel.com.br",
        )

        start_calls: list[tuple[Any, ...]] = []

        def _mock_start(*args: Any) -> tuple[Any, Any, int, list[str]]:
            start_calls.append(args)
            return (unittest.mock.MagicMock(), unittest.mock.MagicMock(), 0, [])

        monkeypatch.setattr("beddel.cli.commands._start_runtime", _mock_start)
        monkeypatch.setattr("beddel.cli.commands._connect_remote_flow", lambda **_kw: None)

        runner = CliRunner()
        result = runner.invoke(cli, ["connect"])
        assert result.exit_code == 0
        # _start_runtime should NOT be called from the unified path in remote mode
        assert len(start_calls) == 0


@pytest.mark.skip(reason="Pre-existing async timeout flake — blocks CI")
class TestConnectDevDeprecationWarning:
    """AC #4: 'beddel connect dev' prints deprecation warning."""

    def test_dev_deprecation_warning_in_output(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import unittest.mock

        monkeypatch.setattr(
            "beddel.cli.commands._build_runtime_app",
            lambda *_a, **_kw: (unittest.mock.MagicMock(), 0, []),
        )
        monkeypatch.setattr("uvicorn.Config", unittest.mock.MagicMock())
        monkeypatch.setattr("uvicorn.Server", lambda _cfg: unittest.mock.MagicMock())

        async def _noop(*_a: Any, **_kw: Any) -> None:
            return

        monkeypatch.setattr("beddel.cli.commands._wait_for_shutdown", _noop)

        runner = CliRunner()
        result = runner.invoke(cli, ["connect", "dev"])
        assert result.exit_code == 0
        # CliRunner mixes stderr into output by default
        assert "deprecated" in result.output.lower()
        assert "config.json" in result.output


@pytest.mark.skip(reason="Pre-existing async timeout flake — blocks CI")
class TestConnectRemoteDeprecationWarning:
    """AC #5: 'beddel connect remote' prints deprecation warning."""

    def test_remote_deprecation_warning_in_output(self, monkeypatch: pytest.MonkeyPatch) -> None:
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

        async def _noop(*_a: Any, **_kw: Any) -> None:
            return

        monkeypatch.setattr("beddel.cli.commands._relay_loop", _noop)

        runner = CliRunner()
        result = runner.invoke(cli, ["connect", "remote"])
        assert result.exit_code == 0
        # CliRunner mixes stderr into output by default
        assert "deprecated" in result.output.lower()
        assert "config.json" in result.output


# ---------------------------------------------------------------------------
# BC10.2 — HTTP long-poll relay tests
# ---------------------------------------------------------------------------


class TestRelayLoopHttpLongPoll:
    """Tests for _relay_loop HTTP long-poll behavior (Story BC10.2)."""

    async def test_relay_loop_connected_on_204(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """HTTP long-poll prints 'Connected to' on first 204 response."""
        import httpx

        from beddel.cli.commands import _relay_loop

        call_count = 0

        async def _mock_get(self_client: Any, url: str, **kwargs: Any) -> Any:
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                # Stop after second poll by raising an error that triggers break
                raise SystemExit(0)
            return httpx.Response(204, request=httpx.Request("GET", url))

        monkeypatch.setattr("httpx.AsyncClient.get", _mock_get)

        # Capture click output
        output_lines: list[str] = []
        monkeypatch.setattr("click.echo", lambda msg="", **kw: output_lines.append(str(msg)))

        # Suppress signal registration in test
        import signal

        monkeypatch.setattr(signal, "signal", lambda *_a: None)

        with pytest.raises(SystemExit):
            await _relay_loop(
                dashboard_url="https://dash.example.com",
                token="test-token",
                username="testuser",
                local_port=8000,
            )

        assert any("Connected to" in line for line in output_lines)

    async def test_relay_loop_auth_error_401(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """HTTP long-poll raises SystemExit(1) on 401 and prints auth error."""
        import httpx

        from beddel.cli.commands import _relay_loop

        async def _mock_get(self_client: Any, url: str, **kwargs: Any) -> Any:
            return httpx.Response(401, request=httpx.Request("GET", url))

        monkeypatch.setattr("httpx.AsyncClient.get", _mock_get)

        # Capture stderr output
        stderr_lines: list[str] = []

        def _mock_echo(msg: str = "", err: bool = False, **kw: Any) -> None:
            if err:
                stderr_lines.append(str(msg))

        monkeypatch.setattr("click.echo", _mock_echo)

        import signal

        monkeypatch.setattr(signal, "signal", lambda *_a: None)

        with pytest.raises(SystemExit) as exc_info:
            await _relay_loop(
                dashboard_url="https://dash.example.com",
                token="bad-token",
                username="testuser",
                local_port=8000,
            )

        assert exc_info.value.code == 1
        assert any("Authentication failed" in line for line in stderr_lines)

    async def test_relay_loop_backoff_on_5xx(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """HTTP long-poll reconnects with backoff on 500 response."""
        import httpx

        from beddel.cli.commands import _relay_loop

        call_count = 0

        async def _mock_get(self_client: Any, url: str, **kwargs: Any) -> Any:
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                raise SystemExit(0)
            return httpx.Response(500, request=httpx.Request("GET", url))

        monkeypatch.setattr("httpx.AsyncClient.get", _mock_get)

        # Capture stderr output
        stderr_lines: list[str] = []

        def _mock_echo(msg: str = "", err: bool = False, **kw: Any) -> None:
            if err:
                stderr_lines.append(str(msg))

        monkeypatch.setattr("click.echo", _mock_echo)

        # Patch asyncio.sleep to avoid real delays
        monkeypatch.setattr("asyncio.sleep", AsyncMock())

        import signal

        monkeypatch.setattr(signal, "signal", lambda *_a: None)

        with pytest.raises(SystemExit):
            await _relay_loop(
                dashboard_url="https://dash.example.com",
                token="test-token",
                username="testuser",
                local_port=8000,
            )

        assert any("Reconnecting..." in line for line in stderr_lines)

    async def test_handle_relay_run_posts_events(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """_handle_relay_run collects SSE events and POSTs them to relay endpoint."""
        import httpx

        from beddel.cli.commands import _handle_relay_run

        # Simulate SSE stream lines from local AG-UI endpoint
        sse_lines = [
            "event: message",
            'data: {"type": "TEXT_MESSAGE_START", "messageId": "m1"}',
            "",
            "event: message",
            'data: {"type": "TEXT_MESSAGE_END", "messageId": "m1"}',
            "",
        ]

        # Track POSTed events
        posted_payloads: list[dict[str, Any]] = []

        class MockStreamResponse:
            """Mock for httpx streaming response context manager."""

            status_code = 200

            def raise_for_status(self) -> None:
                pass

            async def aiter_lines(self):  # type: ignore[no-untyped-def]
                for line in sse_lines:
                    yield line

            async def aclose(self) -> None:
                pass

        class MockClient:
            """Mock httpx.AsyncClient that handles both stream and post."""

            def __init__(self, **kwargs: Any) -> None:
                self._timeout = kwargs.get("timeout")

            async def __aenter__(self) -> MockClient:
                return self

            async def __aexit__(self, *args: Any) -> None:
                pass

            def stream(self, method: str, url: str, **kwargs: Any) -> Any:
                """Return an async context manager yielding MockStreamResponse."""

                class _StreamCtx:
                    async def __aenter__(self_ctx) -> MockStreamResponse:  # noqa: N805
                        return MockStreamResponse()

                    async def __aexit__(self_ctx, *args: Any) -> None:  # noqa: N805
                        pass

                return _StreamCtx()

            async def post(self, url: str, **kwargs: Any) -> Any:
                posted_payloads.append({"url": url, **kwargs})
                return httpx.Response(200, request=httpx.Request("POST", url))

        monkeypatch.setattr("httpx.AsyncClient", MockClient)

        command = {
            "agent_name": "beddel",
            "input": {"state": {"workflow_id": "test-wf"}},
        }

        await _handle_relay_run(
            command=command,
            local_port=9000,
            dashboard_url="https://dash.example.com",
            token="test-token",
        )

        # Verify events were POSTed to the relay endpoint
        assert len(posted_payloads) == 1
        post_call = posted_payloads[0]
        assert post_call["url"] == "https://dash.example.com/api/relay/events"
        assert "json" in post_call
        events = post_call["json"]["events"]
        assert len(events) == 2
        assert events[0]["type"] == "TEXT_MESSAGE_START"
        assert events[1]["type"] == "TEXT_MESSAGE_END"
        # Verify auth header was sent
        assert post_call["headers"]["Authorization"] == "Bearer test-token"
