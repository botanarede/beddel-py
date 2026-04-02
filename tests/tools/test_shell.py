"""Unit tests for beddel_tools_shell.tools — shell_exec tool."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from beddel_tools_shell.tools import shell_exec

from beddel.utils.subprocess import SubprocessResult


class TestShellExecMetadata:
    """Tests for shell_exec tool metadata."""

    def test_has_beddel_tool_metadata(self) -> None:
        meta: dict[str, str] = shell_exec._beddel_tool_meta  # type: ignore[attr-defined]
        assert meta["name"] == "shell_exec"
        assert meta["category"] == "shell"

    def test_has_description(self) -> None:
        meta: dict[str, str] = shell_exec._beddel_tool_meta  # type: ignore[attr-defined]
        assert meta["description"] == "Execute shell command safely"


class TestShellExecExecution:
    """Tests for shell_exec execution behavior."""

    @patch("beddel_tools_shell.tools.SafeSubprocessRunner.run")
    def test_returns_dict_from_subprocess_result(self, mock_run: Any) -> None:
        # Arrange
        mock_run.return_value = SubprocessResult(
            exit_code=0,
            stdout="hello\n",
            stderr="",
            timed_out=False,
            truncated=False,
        )

        # Act
        result = shell_exec(cmd="echo hello")

        # Assert
        assert isinstance(result, dict)
        assert result["exit_code"] == 0
        assert result["stdout"] == "hello\n"
        assert result["stderr"] == ""
        assert result["timed_out"] is False
        assert result["truncated"] is False

    @patch("beddel_tools_shell.tools.SafeSubprocessRunner.run")
    def test_passes_cmd_to_runner(self, mock_run: Any) -> None:
        mock_run.return_value = SubprocessResult(
            exit_code=0,
            stdout="",
            stderr="",
            timed_out=False,
            truncated=False,
        )

        shell_exec(cmd="ls -la")

        mock_run.assert_called_once_with("ls -la", timeout=60, cwd=None)

    @patch("beddel_tools_shell.tools.SafeSubprocessRunner.run")
    def test_passes_custom_timeout(self, mock_run: Any) -> None:
        mock_run.return_value = SubprocessResult(
            exit_code=0,
            stdout="",
            stderr="",
            timed_out=False,
            truncated=False,
        )

        shell_exec(cmd="sleep 1", timeout=120)

        mock_run.assert_called_once_with("sleep 1", timeout=120, cwd=None)

    @patch("beddel_tools_shell.tools.SafeSubprocessRunner.run")
    def test_passes_custom_cwd(self, mock_run: Any) -> None:
        mock_run.return_value = SubprocessResult(
            exit_code=0,
            stdout="",
            stderr="",
            timed_out=False,
            truncated=False,
        )

        shell_exec(cmd="ls", cwd="/tmp")

        mock_run.assert_called_once_with("ls", timeout=60, cwd="/tmp")

    @patch("beddel_tools_shell.tools.SafeSubprocessRunner.run")
    def test_fail_on_error_false_does_not_raise(self, mock_run: Any) -> None:
        mock_run.return_value = SubprocessResult(
            exit_code=1,
            stdout="",
            stderr="error msg",
            timed_out=False,
            truncated=False,
        )

        result = shell_exec(cmd="false", fail_on_error=False)

        assert result["exit_code"] == 1

    @patch("beddel_tools_shell.tools.SafeSubprocessRunner.run")
    def test_fail_on_error_true_raises_on_nonzero(self, mock_run: Any) -> None:
        mock_run.return_value = SubprocessResult(
            exit_code=1,
            stdout="",
            stderr="something failed",
            timed_out=False,
            truncated=False,
        )

        import pytest

        with pytest.raises(RuntimeError, match="something failed"):
            shell_exec(cmd="false", fail_on_error=True)

    @patch("beddel_tools_shell.tools.SafeSubprocessRunner.run")
    def test_fail_on_error_true_does_not_raise_on_zero(self, mock_run: Any) -> None:
        mock_run.return_value = SubprocessResult(
            exit_code=0,
            stdout="ok",
            stderr="",
            timed_out=False,
            truncated=False,
        )

        result = shell_exec(cmd="true", fail_on_error=True)

        assert result["exit_code"] == 0
