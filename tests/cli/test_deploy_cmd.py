"""Unit tests for ``beddel deploy`` CLI command.

Uses Click's CliRunner and mocks the ``beddel_deploy_agent_engine`` kit module
so tests pass without google-adk or GCP access.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from beddel.cli.commands import cli


class TestDeploySuccess:
    """Tests for the success path — ADC configured, deploy succeeds."""

    def test_deploy_prints_resource_and_console_url(self, tmp_path: Path) -> None:
        """Successful deploy prints resource_name and console_url."""
        # Create a temporary flow YAML file
        flow_file = tmp_path / "test-flow.yaml"
        flow_file.write_text("id: test\nname: Test\nsteps: []")

        # Build mock kit module
        mock_kit = MagicMock()
        mock_kit.check_adc.return_value = {
            "configured": True,
            "project_id": "beddel-beta",
            "error": None,
        }

        mock_deploy_result = MagicMock()
        mock_deploy_result.resource_name = (
            "projects/beddel-beta/locations/us-central1/agents/abc123"
        )
        mock_deploy_result.console_url = (
            "https://console.cloud.google.com/gen-app-builder/engines/abc123?project=beddel-beta"
        )
        mock_kit.deploy_flow_to_agent_engine.return_value = mock_deploy_result

        with patch.dict("sys.modules", {"beddel_deploy_agent_engine": mock_kit}):
            runner = CliRunner()
            result = runner.invoke(cli, ["deploy", str(flow_file)])

        assert result.exit_code == 0
        assert "abc123" in result.output
        assert "Deployed successfully" in result.output
        assert "console.cloud.google.com" in result.output

    def test_deploy_calls_check_adc(self, tmp_path: Path) -> None:
        """The deploy command calls check_adc before deploying."""
        flow_file = tmp_path / "test-flow.yaml"
        flow_file.write_text("id: check\nname: Check\nsteps: []")

        mock_kit = MagicMock()
        mock_kit.check_adc.return_value = {
            "configured": True,
            "project_id": "my-project",
            "error": None,
        }

        mock_deploy_result = MagicMock()
        mock_deploy_result.resource_name = "projects/p/locations/r/agents/x"
        mock_deploy_result.console_url = "https://example.com"
        mock_kit.deploy_flow_to_agent_engine.return_value = mock_deploy_result

        with patch.dict("sys.modules", {"beddel_deploy_agent_engine": mock_kit}):
            runner = CliRunner()
            runner.invoke(cli, ["deploy", str(flow_file)])

        mock_kit.check_adc.assert_called_once()

    def test_deploy_passes_options_to_deploy_function(self, tmp_path: Path) -> None:
        """CLI options --project, --region, --staging-bucket are forwarded."""
        flow_file = tmp_path / "my-flow.yaml"
        flow_file.write_text("id: opt\nname: Options\nsteps: []")

        mock_kit = MagicMock()
        mock_kit.check_adc.return_value = {
            "configured": True,
            "project_id": "custom-proj",
            "error": None,
        }

        mock_deploy_result = MagicMock()
        mock_deploy_result.resource_name = "projects/custom-proj/locations/eu/agents/z"
        mock_deploy_result.console_url = (
            "https://console.cloud.google.com/gen-app-builder/engines/z"
        )
        mock_kit.deploy_flow_to_agent_engine.return_value = mock_deploy_result

        with patch.dict("sys.modules", {"beddel_deploy_agent_engine": mock_kit}):
            runner = CliRunner()
            result = runner.invoke(
                cli,
                [
                    "deploy",
                    str(flow_file),
                    "--project",
                    "custom-proj",
                    "--region",
                    "europe-west1",
                    "--staging-bucket",
                    "gs://custom-bucket",
                ],
            )

        assert result.exit_code == 0
        call_kwargs = mock_kit.deploy_flow_to_agent_engine.call_args[1]
        assert call_kwargs["project"] == "custom-proj"
        assert call_kwargs["region"] == "europe-west1"
        assert call_kwargs["staging_bucket"] == "gs://custom-bucket"


class TestDeployAdcFailure:
    """Tests for the ADC failure path — credentials not configured."""

    def test_adc_not_configured_exits_with_error(self, tmp_path: Path) -> None:
        """When check_adc returns configured=False, deploy exits with error."""
        flow_file = tmp_path / "test-flow.yaml"
        flow_file.write_text("id: test\nname: Test\nsteps: []")

        mock_kit = MagicMock()
        mock_kit.check_adc.return_value = {
            "configured": False,
            "project_id": None,
            "error": "ADC not configured. Run: gcloud auth application-default login",
        }

        with patch.dict("sys.modules", {"beddel_deploy_agent_engine": mock_kit}):
            runner = CliRunner()
            result = runner.invoke(cli, ["deploy", str(flow_file)])

        assert result.exit_code == 1
        assert "gcloud auth application-default login" in result.output

    def test_adc_failure_does_not_call_deploy(self, tmp_path: Path) -> None:
        """When ADC fails, deploy_flow_to_agent_engine is never called."""
        flow_file = tmp_path / "test-flow.yaml"
        flow_file.write_text("id: test\nname: Test\nsteps: []")

        mock_kit = MagicMock()
        mock_kit.check_adc.return_value = {
            "configured": False,
            "project_id": None,
            "error": "gcloud CLI not found.",
        }

        with patch.dict("sys.modules", {"beddel_deploy_agent_engine": mock_kit}):
            runner = CliRunner()
            runner.invoke(cli, ["deploy", str(flow_file)])

        mock_kit.deploy_flow_to_agent_engine.assert_not_called()


class TestDeployKitNotInstalled:
    """Tests for when deploy-agent-engine-kit is not installed."""

    def test_kit_missing_exits_with_install_message(self, tmp_path: Path) -> None:
        """When beddel_deploy_agent_engine can't be imported, shows install message."""
        flow_file = tmp_path / "test-flow.yaml"
        flow_file.write_text("id: test\nname: Test\nsteps: []")

        # Patch sys.modules to simulate the kit not being importable
        # Use a side_effect on import to raise ImportError for the kit
        original_import = __import__

        def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
            if name == "beddel_deploy_agent_engine":
                raise ImportError("No module named 'beddel_deploy_agent_engine'")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=fake_import):
            runner = CliRunner()
            result = runner.invoke(cli, ["deploy", str(flow_file)])

        assert result.exit_code == 1
        assert "not installed" in result.output.lower() or "beddel init" in result.output


class TestDeployRuntimeError:
    """Tests for deploy runtime errors (e.g., API failure)."""

    def test_deploy_exception_prints_error(self, tmp_path: Path) -> None:
        """When deploy_flow_to_agent_engine raises, CLI prints error and exits 1."""
        flow_file = tmp_path / "test-flow.yaml"
        flow_file.write_text("id: test\nname: Test\nsteps: []")

        mock_kit = MagicMock()
        mock_kit.check_adc.return_value = {
            "configured": True,
            "project_id": "beddel-beta",
            "error": None,
        }
        mock_kit.deploy_flow_to_agent_engine.side_effect = RuntimeError("API quota exceeded")

        with patch.dict("sys.modules", {"beddel_deploy_agent_engine": mock_kit}):
            runner = CliRunner()
            result = runner.invoke(cli, ["deploy", str(flow_file)])

        assert result.exit_code == 1
        assert "API quota exceeded" in result.output
