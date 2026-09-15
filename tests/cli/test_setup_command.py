"""Tests for the ``beddel launch`` CLI command."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from click.testing import CliRunner

from beddel.cli.commands import cli


def _mock_uvicorn_server_class(open_mock: MagicMock | None = None):
    """Create a mock uvicorn.Server that simulates the started lifecycle."""

    class _FakeServer:
        def __init__(self, config):
            self.config = config
            self.started = False

        async def serve(self):
            # Simulate server becoming ready immediately
            self.started = True

    return _FakeServer


# ---------------------------------------------------------------------------
# Pre-flight: consent before anything is written
# ---------------------------------------------------------------------------


def test_launch_without_tty_names_non_interactive_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With no terminal to ask on, launch refuses and names ``beddel init``."""
    monkeypatch.setattr("beddel.cli.init.is_bootstrapped", lambda: False)
    monkeypatch.setattr("beddel.cli.init._stdin_is_tty", lambda: False)

    result = CliRunner().invoke(cli, ["launch"])

    assert result.exit_code != 0
    assert "beddel init" in result.output
    assert "--provider" in result.output
    assert "--kits-dir" in result.output


def test_launch_declined_writes_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Answering no to the consent prompt aborts without touching anything."""
    monkeypatch.setattr("beddel.cli.init.is_bootstrapped", lambda: False)
    monkeypatch.setattr("beddel.cli.init._stdin_is_tty", lambda: True)

    wrote: list[str] = []
    monkeypatch.setattr(
        "beddel.cli.init._persist_kits_dir",
        lambda _dir: wrote.append("kits_paths"),
    )
    monkeypatch.setattr(
        "beddel.cli.init.initialize",
        lambda *_a, **_k: wrote.append("initialize"),
    )

    # provider, kits dir, then decline
    result = CliRunner().invoke(cli, ["launch"], input="gemini\n/tmp/beddel-kits\nn\n")

    assert result.exit_code == 0
    assert "nothing was written" in result.output
    assert wrote == []


def test_launch_accepted_persists_and_initializes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Accepting records the chosen kits directory and bootstraps once."""
    monkeypatch.setattr("beddel.cli.init.is_bootstrapped", lambda: False)
    monkeypatch.setattr("beddel.cli.init._stdin_is_tty", lambda: True)

    persisted: list[Path] = []
    initialized: list[tuple[str, Path]] = []
    monkeypatch.setattr("beddel.cli.init._persist_kits_dir", persisted.append)
    monkeypatch.setattr(
        "beddel.cli.init.initialize",
        lambda provider, kits_dir, **_k: initialized.append((provider, kits_dir)),
    )
    monkeypatch.setattr("beddel.cli.config.is_onboarding_complete", lambda: False)
    monkeypatch.setattr(
        "beddel.cli.commands._build_runtime_app",
        lambda *_a, **_k: (object(), 1, ["beddel_setup"]),
    )
    monkeypatch.setattr("uvicorn.Server", _mock_uvicorn_server_class())

    kits_dir = tmp_path / "chosen-kits"
    result = CliRunner().invoke(
        cli,
        ["launch", "--no-browser", "--port", "8099"],
        input=f"litellm\n{kits_dir}\ny\n",
    )

    assert result.exit_code == 0
    assert persisted == [kits_dir]
    assert initialized == [("litellm", kits_dir)]
    assert kits_dir.is_dir(), "the chosen directory is created on accept"


def test_launch_prompt_lists_provider_kit_with_reason(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The prompt discloses every kit it will install, and why."""
    monkeypatch.setattr("beddel.cli.init.is_bootstrapped", lambda: False)
    monkeypatch.setattr("beddel.cli.init._stdin_is_tty", lambda: True)
    monkeypatch.setattr("beddel.cli.init._persist_kits_dir", lambda _d: None)
    monkeypatch.setattr("beddel.cli.init.initialize", lambda *_a, **_k: None)

    result = CliRunner().invoke(
        cli, ["launch"], input=f"litellm\n{tmp_path / 'k'}\nn\n"
    )

    assert "serve-fastapi-kit" in result.output
    assert "ag-ui-kit" in result.output
    assert "provider-litellm-kit" in result.output
    # The reason for each kit is shown, not just its name
    assert "HTTP server" in result.output


# ---------------------------------------------------------------------------
# Serving: the first run serves the wizard alone
# ---------------------------------------------------------------------------


def test_launch_serves_example_workflows_not_setup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The browser gets the usage examples; the setup wizard stays in the terminal."""
    monkeypatch.setattr("beddel.cli.init.is_bootstrapped", lambda: True)

    calls: list[dict] = []

    def _capture(paths, **kwargs):
        calls.append({"paths": paths, **kwargs})
        return (object(), 3, ["hello_agent", "sum_two_numbers", "create_workflow"])

    monkeypatch.setattr("beddel.cli.commands._build_runtime_app", _capture)
    monkeypatch.setattr("uvicorn.Server", _mock_uvicorn_server_class())
    open_mock = MagicMock()
    monkeypatch.setattr("webbrowser.open", open_mock)

    result = CliRunner().invoke(cli, ["launch", "--no-browser", "--port", "8099"])

    assert result.exit_code == 0
    names = [p.name for p in calls[0]["paths"]]
    assert "setup.yaml" not in names, "the setup wizard must not reach the browser"
    assert "hello.yaml" in names
    assert "sum-two-numbers.yaml" in names
    assert "create-workflow.yaml" in names
    open_mock.assert_not_called()


def test_launch_reports_the_flow_count(monkeypatch: pytest.MonkeyPatch) -> None:
    """Launch reports how many flows it mounted."""
    monkeypatch.setattr("beddel.cli.init.is_bootstrapped", lambda: True)
    monkeypatch.setattr(
        "beddel.cli.commands._build_runtime_app",
        lambda *_a, **_k: (object(), 3, ["flow_a", "flow_b", "flow_c"]),
    )
    monkeypatch.setattr("uvicorn.Server", _mock_uvicorn_server_class())

    result = CliRunner().invoke(cli, ["launch", "--no-browser", "--port", "8088"])

    assert result.exit_code == 0
    assert "3 flow(s)" in result.output


def test_launch_opens_browser(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default behaviour opens the browser after server starts."""
    monkeypatch.setattr("beddel.cli.init.is_bootstrapped", lambda: True)
    monkeypatch.setattr(
        "beddel.cli.commands._build_runtime_app",
        lambda *_a, **_k: (object(), 3, ["hello_agent"]),
    )
    monkeypatch.setattr("uvicorn.Server", _mock_uvicorn_server_class())
    open_mock = MagicMock()
    monkeypatch.setattr("webbrowser.open", open_mock)

    result = CliRunner().invoke(cli, ["launch", "--port", "8088"])

    assert result.exit_code == 0
    open_mock.assert_called_once_with("http://localhost:8088")
