"""Beddel gate tools — validation gate wrappers over shell_exec.

Provides thin wrappers for pytest, ruff check, ruff format, and mypy
that call :func:`~beddel.tools.shell.shell_exec` with ``fail_on_error=True``.
"""

from __future__ import annotations

from typing import Any

from beddel.tools import beddel_tool
from beddel.tools.shell import shell_exec


@beddel_tool(name="pytest_run", description="Run pytest", category="gates")
def pytest_run(cmd: str = "pytest -x --timeout=30") -> dict[str, Any]:
    """Run pytest with fail-on-error.

    Args:
        cmd: Pytest command to execute. Default ``"pytest -x --timeout=30"``.

    Returns:
        Dict representation of SubprocessResult.

    Raises:
        RuntimeError: When the command exits with non-zero code.
    """
    return shell_exec(cmd=cmd, fail_on_error=True)


@beddel_tool(name="ruff_check", description="Run ruff check", category="gates")
def ruff_check(cmd: str = "ruff check .") -> dict[str, Any]:
    """Run ruff linter with fail-on-error.

    Args:
        cmd: Ruff check command to execute. Default ``"ruff check ."``.

    Returns:
        Dict representation of SubprocessResult.

    Raises:
        RuntimeError: When the command exits with non-zero code.
    """
    return shell_exec(cmd=cmd, fail_on_error=True)


@beddel_tool(name="ruff_format", description="Run ruff format check", category="gates")
def ruff_format(cmd: str = "ruff format --check .") -> dict[str, Any]:
    """Run ruff formatter check with fail-on-error.

    Args:
        cmd: Ruff format command to execute. Default ``"ruff format --check ."``.

    Returns:
        Dict representation of SubprocessResult.

    Raises:
        RuntimeError: When the command exits with non-zero code.
    """
    return shell_exec(cmd=cmd, fail_on_error=True)


@beddel_tool(name="mypy_check", description="Run mypy type check", category="gates")
def mypy_check(cmd: str = "mypy .") -> dict[str, Any]:
    """Run mypy type checker with fail-on-error.

    Args:
        cmd: Mypy command to execute. Default ``"mypy ."``.

    Returns:
        Dict representation of SubprocessResult.

    Raises:
        RuntimeError: When the command exits with non-zero code.
    """
    return shell_exec(cmd=cmd, fail_on_error=True)
