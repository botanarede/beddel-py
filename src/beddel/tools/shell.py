"""Beddel shell tool — safe subprocess execution.

Provides :func:`shell_exec`, a builtin tool that wraps
:class:`~beddel.utils.subprocess.SafeSubprocessRunner` with the
``@beddel_tool`` decorator for auto-discovery.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from beddel.tools import beddel_tool
from beddel.utils.subprocess import SafeSubprocessRunner


@beddel_tool(name="shell_exec", description="Execute shell command safely", category="shell")
def shell_exec(
    cmd: str,
    *,
    timeout: int = 60,
    cwd: str | None = None,
    fail_on_error: bool = False,
) -> dict[str, Any]:
    """Execute a shell command safely via SafeSubprocessRunner.

    Args:
        cmd: Shell command string to execute.
        timeout: Maximum execution time in seconds. Default 60.
        cwd: Working directory for the subprocess.
        fail_on_error: If True, raise RuntimeError on non-zero exit code.

    Returns:
        Dict representation of SubprocessResult with keys: exit_code,
        stdout, stderr, timed_out, truncated.

    Raises:
        RuntimeError: When fail_on_error is True and exit_code != 0.
    """
    result = SafeSubprocessRunner.run(cmd, timeout=timeout, cwd=cwd)
    if fail_on_error and result.exit_code != 0:
        raise RuntimeError(result.stderr)
    return asdict(result)
