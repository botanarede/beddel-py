"""Safe subprocess execution utility.

Provides :class:`SafeSubprocessRunner` — a security-hardened wrapper around
:func:`subprocess.run` with ``shell=False``, automatic ``shlex.split()``,
configurable timeout, and output truncation.
"""

from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass

__all__ = ["SafeSubprocessRunner", "SubprocessResult"]


@dataclass
class SubprocessResult:
    """Result of a safe subprocess execution.

    Attributes:
        exit_code: Process exit code. -1 if timed out before completion.
        stdout: Captured standard output (may be truncated).
        stderr: Captured standard error (may be truncated).
        timed_out: True if the process exceeded the timeout.
        truncated: True if stdout or stderr was truncated.
    """

    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool
    truncated: bool


class SafeSubprocessRunner:
    """Safe subprocess execution utility.

    Wraps subprocess.run with security defaults:
    - shell=False always (prevents shell injection)
    - shlex.split() for string commands
    - Configurable timeout (default 60s)
    - Output truncation (default 1MB per stream)

    This is a utility class, not a port. It provides safe defaults
    for subprocess-based tool implementations.

    Note:
        Truncation uses character count (not byte count) for simplicity.
        This is acceptable for v0.1 — byte-accurate truncation can be
        added later if needed.
    """

    @staticmethod
    def run(
        command: str | list[str],
        *,
        timeout: int = 60,
        max_output_bytes: int = 1_048_576,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
    ) -> SubprocessResult:
        """Execute a command safely with timeout and output limits.

        Args:
            command: Command to execute. If str, split with shlex.split().
            timeout: Maximum execution time in seconds. Default 60.
            max_output_bytes: Maximum characters per output stream. Default 1MB.
                Uses character count for simplicity (see class docstring).
            cwd: Working directory for the subprocess.
            env: Environment variables for the subprocess.

        Returns:
            SubprocessResult with exit code, output, and status flags.
        """
        cmd = shlex.split(command) if isinstance(command, str) else command

        timed_out = False
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                shell=False,  # noqa: S603 — intentionally False for security
                cwd=cwd,
                env=env,
            )
            stdout = result.stdout or ""
            stderr = result.stderr or ""
            exit_code = result.returncode
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            stdout = _decode_partial(exc.stdout)
            stderr = _decode_partial(exc.stderr)
            exit_code = -1

        truncated = False
        stdout, was_truncated = _truncate(stdout, max_output_bytes)
        truncated = truncated or was_truncated
        stderr, was_truncated = _truncate(stderr, max_output_bytes)
        truncated = truncated or was_truncated

        return SubprocessResult(
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            timed_out=timed_out,
            truncated=truncated,
        )


def _decode_partial(value: str | bytes | None) -> str:
    """Decode partial output from a ``TimeoutExpired`` exception.

    ``subprocess.TimeoutExpired`` may carry ``stdout``/``stderr`` as
    ``str``, ``bytes``, or ``None`` depending on the platform and whether
    ``text=True`` was honoured.
    """
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _truncate(text: str, max_chars: int) -> tuple[str, bool]:
    """Truncate *text* to *max_chars* characters.

    Returns:
        A ``(text, was_truncated)`` tuple. When truncated, a notice is
        appended to the output.
    """
    if len(text) <= max_chars:
        return text, False
    return (
        text[:max_chars] + f"\n[truncated: output exceeded {max_chars} bytes]",
        True,
    )
