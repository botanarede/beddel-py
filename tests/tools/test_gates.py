"""Unit tests for beddel_tools_gates.tools — validation gate tools."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from beddel_tools_gates.tools import mypy_check, pytest_run, ruff_check, ruff_format


class TestGateToolMetadata:
    """Tests for gate tool metadata."""

    def test_pytest_run_metadata(self) -> None:
        meta: dict[str, str] = pytest_run._beddel_tool_meta  # type: ignore[attr-defined]
        assert meta["name"] == "pytest_run"
        assert meta["category"] == "gates"

    def test_ruff_check_metadata(self) -> None:
        meta: dict[str, str] = ruff_check._beddel_tool_meta  # type: ignore[attr-defined]
        assert meta["name"] == "ruff_check"
        assert meta["category"] == "gates"

    def test_ruff_format_metadata(self) -> None:
        meta: dict[str, str] = ruff_format._beddel_tool_meta  # type: ignore[attr-defined]
        assert meta["name"] == "ruff_format"
        assert meta["category"] == "gates"

    def test_mypy_check_metadata(self) -> None:
        meta: dict[str, str] = mypy_check._beddel_tool_meta  # type: ignore[attr-defined]
        assert meta["name"] == "mypy_check"
        assert meta["category"] == "gates"


class TestGateToolDefaults:
    """Tests for gate tools using default commands."""

    @patch("beddel_tools_gates.tools.shell_exec")
    def test_pytest_run_default_cmd(self, mock_shell: Any) -> None:
        mock_shell.return_value = {"exit_code": 0, "stdout": "", "stderr": ""}

        pytest_run()

        mock_shell.assert_called_once_with(
            cmd="pytest -x --timeout=30",
            fail_on_error=True,
        )

    @patch("beddel_tools_gates.tools.shell_exec")
    def test_ruff_check_default_cmd(self, mock_shell: Any) -> None:
        mock_shell.return_value = {"exit_code": 0, "stdout": "", "stderr": ""}

        ruff_check()

        mock_shell.assert_called_once_with(cmd="ruff check .", fail_on_error=True)

    @patch("beddel_tools_gates.tools.shell_exec")
    def test_ruff_format_default_cmd(self, mock_shell: Any) -> None:
        mock_shell.return_value = {"exit_code": 0, "stdout": "", "stderr": ""}

        ruff_format()

        mock_shell.assert_called_once_with(
            cmd="ruff format --check .",
            fail_on_error=True,
        )

    @patch("beddel_tools_gates.tools.shell_exec")
    def test_mypy_check_default_cmd(self, mock_shell: Any) -> None:
        mock_shell.return_value = {"exit_code": 0, "stdout": "", "stderr": ""}

        mypy_check()

        mock_shell.assert_called_once_with(cmd="mypy .", fail_on_error=True)


class TestGateToolCustomCmd:
    """Tests for gate tools with custom command overrides."""

    @patch("beddel_tools_gates.tools.shell_exec")
    def test_pytest_run_custom_cmd(self, mock_shell: Any) -> None:
        mock_shell.return_value = {"exit_code": 0, "stdout": "", "stderr": ""}

        pytest_run(cmd="pytest -v tests/")

        mock_shell.assert_called_once_with(
            cmd="pytest -v tests/",
            fail_on_error=True,
        )

    @patch("beddel_tools_gates.tools.shell_exec")
    def test_ruff_check_custom_cmd(self, mock_shell: Any) -> None:
        mock_shell.return_value = {"exit_code": 0, "stdout": "", "stderr": ""}

        ruff_check(cmd="ruff check src/")

        mock_shell.assert_called_once_with(cmd="ruff check src/", fail_on_error=True)


class TestGateToolErrorPropagation:
    """Tests that gate tools propagate RuntimeError from shell_exec."""

    @patch("beddel_tools_gates.tools.shell_exec")
    def test_pytest_run_propagates_runtime_error(self, mock_shell: Any) -> None:
        mock_shell.side_effect = RuntimeError("tests failed")

        import pytest

        with pytest.raises(RuntimeError, match="tests failed"):
            pytest_run()

    @patch("beddel_tools_gates.tools.shell_exec")
    def test_ruff_check_propagates_runtime_error(self, mock_shell: Any) -> None:
        mock_shell.side_effect = RuntimeError("lint errors")

        import pytest

        with pytest.raises(RuntimeError, match="lint errors"):
            ruff_check()
