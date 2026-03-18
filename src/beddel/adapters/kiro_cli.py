"""Kiro CLI agent adapter — subprocess-based agent execution via ``kiro-cli``.

This adapter bridges the Beddel domain core to the Kiro CLI, enabling
agent-style interactions through the ``kiro-cli chat --no-interactive``
command.  It implements the :class:`~beddel.domain.ports.IAgentAdapter`
protocol via structural subtyping (no explicit inheritance).

The CLI is auto-discovered from ``~/.local/bin/kiro-cli`` when no explicit
path is provided.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

from beddel.domain.errors import AgentError
from beddel.domain.models import AgentResult
from beddel.error_codes import (
    AGENT_EXECUTION_FAILED,
    AGENT_STREAM_INTERRUPTED,
    AGENT_TIMEOUT,
)

__all__ = ["KiroCLIAgentAdapter"]

_DEFAULT_CLI_PATH = Path.home() / ".local" / "bin" / "kiro-cli"


class KiroCLIAgentAdapter:
    """Kiro CLI agent adapter using subprocess execution.

    Implements the ``IAgentAdapter`` protocol structurally by exposing
    :meth:`execute` and :meth:`stream` with matching signatures.  All
    interaction with the Kiro CLI happens through
    ``asyncio.create_subprocess_exec``.

    Args:
        model: Default model identifier for CLI invocations.
        cli_path: Explicit path to the ``kiro-cli`` binary.  When ``None``,
            auto-discovered from ``~/.local/bin/kiro-cli``.
        timeout: Maximum execution time in seconds before the subprocess
            is killed.
    """

    def __init__(
        self,
        model: str = "claude-sonnet-4.6",
        cli_path: Path | None = None,
        timeout: int = 600,
    ) -> None:
        self._model = model
        self._cli_path = cli_path or _DEFAULT_CLI_PATH
        self._timeout = timeout

    # ------------------------------------------------------------------
    # IAgentAdapter.execute
    # ------------------------------------------------------------------

    async def execute(
        self,
        prompt: str,
        *,
        model: str | None = None,
        sandbox: str = "read-only",
        tools: list[str] | None = None,
        output_schema: dict[str, Any] | None = None,
    ) -> AgentResult:
        """Execute a prompt via ``kiro-cli chat --no-interactive``.

        Spawns the CLI as an async subprocess, captures stdout/stderr,
        and returns a structured :class:`AgentResult`.

        Args:
            prompt: The instruction or task to send to the agent.
            model: Optional model override.  Falls back to the adapter's
                configured model when ``None``.
            sandbox: Sandbox access level.  ``"read-only"`` appends
                ``--trust-tools=`` (empty value), ``"workspace-write"``
                and ``"danger-full-access"`` append ``-a``.
            tools: Optional list of tool/agent config names.  When a
                single-element list is provided, appends
                ``--agent <name>``.
            output_schema: Optional JSON Schema dict (currently unused
                by the CLI backend).

        Returns:
            An :class:`AgentResult` with the CLI's stdout, exit code,
            and execution metadata.

        Raises:
            AgentError: ``BEDDEL-AGENT-702`` on timeout, or
                ``BEDDEL-AGENT-701`` on non-zero exit code.
        """
        model_used = model or self._model
        cmd = self._build_command(prompt, model=model_used, sandbox=sandbox, tools=tools)

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(),
                timeout=self._timeout,
            )
        except TimeoutError as exc:
            proc.kill()
            await proc.wait()
            raise AgentError(
                code=AGENT_TIMEOUT,
                message=f"Kiro CLI process timed out after {self._timeout}s",
                details={"timeout": self._timeout, "cmd": [str(c) for c in cmd]},
            ) from exc

        stdout_text = stdout_bytes.decode("utf-8", errors="replace") if stdout_bytes else ""
        stderr_text = stderr_bytes.decode("utf-8", errors="replace") if stderr_bytes else ""

        if proc.returncode != 0:
            raise AgentError(
                code=AGENT_EXECUTION_FAILED,
                message=f"Kiro CLI exited with code {proc.returncode}",
                details={
                    "exit_code": proc.returncode,
                    "stderr": stderr_text,
                    "cmd": [str(c) for c in cmd],
                },
            )

        return AgentResult(
            exit_code=proc.returncode,
            output=stdout_text,
            events=[],
            files_changed=[],
            usage={"model": model_used, "timeout": self._timeout},
            agent_id="kiro-cli",
        )

    # ------------------------------------------------------------------
    # IAgentAdapter.stream
    # ------------------------------------------------------------------

    async def stream(
        self,
        prompt: str,
        *,
        model: str | None = None,
        sandbox: str = "read-only",
        tools: list[str] | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Stream events from the Kiro CLI agent.

        Since the CLI subprocess does not support true streaming, this
        method calls :meth:`execute` internally and yields a single
        ``"complete"`` event with the full output.

        Args:
            prompt: The instruction or task to send to the agent.
            model: Optional model override.  Falls back to the adapter's
                configured model when ``None``.
            sandbox: Sandbox access level for the agent execution.
            tools: Optional list of tool/agent config names.

        Yields:
            A single event dict with keys ``"type"``, ``"output"``, and
            ``"exit_code"``.

        Raises:
            AgentError: ``BEDDEL-AGENT-703`` if the underlying execution
                times out (re-raised from ``BEDDEL-AGENT-702``).

        Note:
            This adapter emits exactly one terminal event per call because
            the CLI subprocess does not support incremental streaming.
            Callers expecting token-level or chunk-level events should be
            aware of this limitation.
        """
        try:
            result = await self.execute(prompt, model=model, sandbox=sandbox, tools=tools)
        except AgentError as exc:
            if exc.code == AGENT_TIMEOUT:
                raise AgentError(
                    code=AGENT_STREAM_INTERRUPTED,
                    message="Kiro CLI stream interrupted due to timeout",
                    details=exc.details,
                ) from exc
            raise
        yield {
            "type": "complete",
            "output": result.output,
            "exit_code": result.exit_code,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_command(
        self,
        prompt: str,
        *,
        model: str,
        sandbox: str,
        tools: list[str] | None,
    ) -> list[str]:
        """Build the CLI argument list for ``kiro-cli chat``.

        Args:
            prompt: The prompt text (appended as the final positional arg).
            model: Model identifier to pass via ``--model``.
            sandbox: Sandbox level controlling trust flags.
            tools: Optional tool/agent config names.

        Returns:
            A list of string arguments suitable for
            ``asyncio.create_subprocess_exec``.

        Raises:
            AgentError: ``BEDDEL-AGENT-701`` if ``sandbox`` is not a
                recognized value, or if ``tools`` contains more than one
                element (CLI supports at most one ``--agent`` flag).
        """
        cmd: list[str] = [str(self._cli_path), "chat", "--no-interactive"]

        # Sandbox mapping
        if sandbox == "read-only":
            cmd.append("--trust-tools=")
        elif sandbox in ("workspace-write", "danger-full-access"):
            cmd.append("-a")
        else:
            raise AgentError(
                code=AGENT_EXECUTION_FAILED,
                message=f"Unsupported sandbox value: {sandbox!r}",
                details={
                    "sandbox": sandbox,
                    "supported": [
                        "read-only",
                        "workspace-write",
                        "danger-full-access",
                    ],
                },
            )

        # Model
        cmd.extend(["--model", model])

        # Tools → --agent (CLI supports at most one --agent flag)
        if tools:
            if len(tools) > 1:
                raise AgentError(
                    code=AGENT_EXECUTION_FAILED,
                    message=f"Kiro CLI supports at most one agent, got {len(tools)}",
                    details={"tools": tools},
                )
            cmd.extend(["--agent", tools[0]])

        # Prompt as final positional argument
        cmd.append(prompt)

        return cmd
