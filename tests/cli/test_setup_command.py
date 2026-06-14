"""Tests for the ``beddel launch`` CLI command."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from click.testing import CliRunner

from beddel.cli.commands import cli


def test_launch_requires_init(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Running launch before init shows a helpful error and exits non-zero."""
    monkeypatch.setattr(
        "beddel.adapters.index_store._DEFAULT_DB_PATH",
        tmp_path / "missing" / "index.db",
    )
    result = CliRunner().invoke(cli, ["launch"])
    assert result.exit_code != 0
    assert "beddel init" in result.output


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


def test_launch_no_browser_first_run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """First run (no onboarding) serves only the onboarding wizard."""
    db = tmp_path / "index.db"
    db.write_text("")
    monkeypatch.setattr("beddel.adapters.index_store._DEFAULT_DB_PATH", db)
    monkeypatch.setattr("beddel.cli.config.is_onboarding_complete", lambda: False)
    monkeypatch.setattr(
        "beddel.cli.commands._build_runtime_app",
        lambda *_a, **_k: (object(), 1, ["beddel_onboarding"]),
    )
    monkeypatch.setattr("uvicorn.Server", _mock_uvicorn_server_class())
    open_mock = MagicMock()
    monkeypatch.setattr("webbrowser.open", open_mock)

    result = CliRunner().invoke(cli, ["launch", "--no-browser", "--port", "8099"])

    assert result.exit_code == 0
    assert "Launch" in result.output
    open_mock.assert_not_called()


def test_launch_post_onboarding(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """After onboarding, launch serves all discovered flows."""
    db = tmp_path / "index.db"
    db.write_text("")
    monkeypatch.setattr("beddel.adapters.index_store._DEFAULT_DB_PATH", db)
    monkeypatch.setattr("beddel.cli.config.is_onboarding_complete", lambda: True)
    monkeypatch.setattr(
        "beddel.cli.commands._build_runtime_app",
        lambda *_a, **_k: (object(), 3, ["flow_a", "flow_b", "flow_c"]),
    )
    monkeypatch.setattr("uvicorn.Server", _mock_uvicorn_server_class())

    result = CliRunner().invoke(cli, ["launch", "--no-browser", "--port", "8088"])

    assert result.exit_code == 0
    assert "Launch" in result.output
    assert "3 flow(s)" in result.output


def test_launch_opens_browser(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Default behaviour opens the browser after server starts."""
    db = tmp_path / "index.db"
    db.write_text("")
    monkeypatch.setattr("beddel.adapters.index_store._DEFAULT_DB_PATH", db)
    monkeypatch.setattr("beddel.cli.config.is_onboarding_complete", lambda: True)
    monkeypatch.setattr(
        "beddel.cli.commands._build_runtime_app",
        lambda *_a, **_k: (object(), 1, ["beddel_onboarding"]),
    )
    monkeypatch.setattr("uvicorn.Server", _mock_uvicorn_server_class())
    open_mock = MagicMock()
    monkeypatch.setattr("webbrowser.open", open_mock)

    result = CliRunner().invoke(cli, ["launch", "--port", "8088"])

    assert result.exit_code == 0
    open_mock.assert_called_once_with("http://localhost:8088")
