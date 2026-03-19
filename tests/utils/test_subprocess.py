"""Unit tests for beddel.utils.subprocess module."""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

from beddel.utils.subprocess import SafeSubprocessRunner

# ---------------------------------------------------------------------------
# Tests: SafeSubprocessRunner
# ---------------------------------------------------------------------------


class TestSafeSubprocessRunner:
    """Tests for SafeSubprocessRunner utility."""

    def test_successful_execution(self) -> None:
        """Run ``echo hello`` and verify successful result fields."""
        result = SafeSubprocessRunner.run("echo hello")

        assert result.exit_code == 0
        assert "hello" in result.stdout
        assert result.timed_out is False
        assert result.truncated is False

    @patch("beddel.utils.subprocess.subprocess.run")
    def test_string_command_split_with_shlex(self, mock_run: MagicMock) -> None:
        """String command is split via shlex into a list."""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        SafeSubprocessRunner.run("echo hello world")

        args, _kwargs = mock_run.call_args
        assert args[0] == ["echo", "hello", "world"]

    @patch("beddel.utils.subprocess.subprocess.run")
    def test_list_command_passed_directly(self, mock_run: MagicMock) -> None:
        """List command is forwarded as-is without shlex splitting."""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        SafeSubprocessRunner.run(["echo", "hello"])

        args, _kwargs = mock_run.call_args
        assert args[0] == ["echo", "hello"]

    @patch("beddel.utils.subprocess.subprocess.run")
    def test_shell_false_enforcement(self, mock_run: MagicMock) -> None:
        """subprocess.run is always called with shell=False."""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        SafeSubprocessRunner.run("echo hi")

        _args, kwargs = mock_run.call_args
        assert kwargs["shell"] is False

    @patch("beddel.utils.subprocess.subprocess.run")
    def test_timeout_handling(self, mock_run: MagicMock) -> None:
        """TimeoutExpired results in timed_out=True and exit_code=-1."""
        mock_run.side_effect = subprocess.TimeoutExpired(
            cmd="sleep 100", timeout=1, output=None, stderr=None
        )

        result = SafeSubprocessRunner.run("sleep 100", timeout=1)

        assert result.timed_out is True
        assert result.exit_code == -1

    @patch("beddel.utils.subprocess.subprocess.run")
    def test_output_truncation_stdout(self, mock_run: MagicMock) -> None:
        """Stdout exceeding max_output_bytes is truncated with marker."""
        big_stdout = "x" * 200
        mock_run.return_value = MagicMock(returncode=0, stdout=big_stdout, stderr="")

        result = SafeSubprocessRunner.run("echo big", max_output_bytes=100)

        assert result.truncated is True
        assert len(result.stdout.split("\n")[0]) == 100
        assert "[truncated: output exceeded 100 bytes]" in result.stdout

    @patch("beddel.utils.subprocess.subprocess.run")
    def test_output_truncation_stderr(self, mock_run: MagicMock) -> None:
        """Stderr exceeding max_output_bytes is truncated with marker."""
        big_stderr = "e" * 200
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr=big_stderr)

        result = SafeSubprocessRunner.run("echo big", max_output_bytes=100)

        assert result.truncated is True
        assert "[truncated: output exceeded 100 bytes]" in result.stderr

    @patch("beddel.utils.subprocess.subprocess.run")
    def test_no_truncation_within_limit(self, mock_run: MagicMock) -> None:
        """Output within max_output_bytes is not truncated."""
        mock_run.return_value = MagicMock(returncode=0, stdout="short", stderr="brief")

        result = SafeSubprocessRunner.run("echo short", max_output_bytes=1000)

        assert result.truncated is False
        assert result.stdout == "short"
        assert result.stderr == "brief"

    def test_non_zero_exit_code(self) -> None:
        """Command that fails returns non-zero exit code."""
        result = SafeSubprocessRunner.run("false")

        assert result.exit_code != 0
        assert result.timed_out is False

    @patch("beddel.utils.subprocess.subprocess.run")
    def test_cwd_passed_to_subprocess(self, mock_run: MagicMock) -> None:
        """cwd kwarg is forwarded to subprocess.run."""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        SafeSubprocessRunner.run("ls", cwd="/tmp")

        _args, kwargs = mock_run.call_args
        assert kwargs["cwd"] == "/tmp"

    @patch("beddel.utils.subprocess.subprocess.run")
    def test_env_passed_to_subprocess(self, mock_run: MagicMock) -> None:
        """env kwarg is forwarded to subprocess.run."""
        custom_env = {"MY_VAR": "value"}
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        SafeSubprocessRunner.run("echo hi", env=custom_env)

        _args, kwargs = mock_run.call_args
        assert kwargs["env"] == {"MY_VAR": "value"}

    @patch("beddel.utils.subprocess.subprocess.run")
    def test_timeout_partial_output(self, mock_run: MagicMock) -> None:
        """TimeoutExpired with partial bytes output is decoded correctly."""
        mock_run.side_effect = subprocess.TimeoutExpired(
            cmd="slow",
            timeout=1,
            output=b"partial stdout",
            stderr=b"partial stderr",
        )

        result = SafeSubprocessRunner.run("slow", timeout=1)

        assert result.timed_out is True
        assert result.stdout == "partial stdout"
        assert result.stderr == "partial stderr"
        assert result.exit_code == -1
