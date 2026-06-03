"""Tests for the ``beddel setup`` CLI command."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from click.testing import CliRunner

from beddel.cli.commands import cli


def test_setup_requires_init(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Running setup before init shows a helpful error and exits non-zero."""
    monkeypatch.setattr(
        "beddel.adapters.index_store._DEFAULT_DB_PATH",
        tmp_path / "missing" / "index.db",
    )
    result = CliRunner().invoke(cli, ["setup"])
    assert result.exit_code != 0
    assert "beddel init" in result.output


def test_setup_no_browser(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """--no-browser starts the server without opening the browser."""
    db = tmp_path / "index.db"
    db.write_text("")
    monkeypatch.setattr("beddel.adapters.index_store._DEFAULT_DB_PATH", db)
    monkeypatch.setattr(
        "beddel.cli.commands._build_runtime_app",
        lambda *_a, **_k: (object(), 1, ["beddel_onboarding"]),
    )
    run_mock = MagicMock()
    monkeypatch.setattr("uvicorn.run", run_mock)
    open_mock = MagicMock()
    monkeypatch.setattr("webbrowser.open", open_mock)

    result = CliRunner().invoke(cli, ["setup", "--no-browser", "--port", "8099"])

    assert result.exit_code == 0
    run_mock.assert_called_once()
    open_mock.assert_not_called()


def test_setup_opens_browser(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Default behaviour schedules a browser open at the served URL."""
    db = tmp_path / "index.db"
    db.write_text("")
    monkeypatch.setattr("beddel.adapters.index_store._DEFAULT_DB_PATH", db)
    monkeypatch.setattr(
        "beddel.cli.commands._build_runtime_app",
        lambda *_a, **_k: (object(), 1, ["beddel_onboarding"]),
    )
    monkeypatch.setattr("uvicorn.run", MagicMock())
    open_mock = MagicMock()
    monkeypatch.setattr("webbrowser.open", open_mock)

    # Run the scheduled Timer callback immediately.
    class _ImmediateTimer:
        def __init__(self, _delay: float, fn: Any, args: Any = None, kwargs: Any = None) -> None:
            self._fn, self._args = fn, args or []

        def start(self) -> None:
            self._fn(*self._args)

    monkeypatch.setattr("threading.Timer", _ImmediateTimer)

    result = CliRunner().invoke(cli, ["setup", "--port", "8088"])

    assert result.exit_code == 0
    open_mock.assert_called_once_with("http://localhost:8088")
