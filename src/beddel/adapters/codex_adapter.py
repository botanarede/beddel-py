"""Codex agent adapter — Docker-based agent execution via ``codex exec``.

This adapter bridges the Beddel domain core to the OpenAI Codex CLI,
enabling agent-style interactions through a Docker-isolated ``codex exec
--json --full-auto`` subprocess.  It implements the
:class:`~beddel.domain.ports.IAgentAdapter` protocol via structural
subtyping (no explicit inheritance).

The Codex CLI runs inside a ``codex-universal`` Docker container with
configurable sandbox isolation (read-only, workspace-write, or
danger-full-access).  Network access is disabled at the Docker level
(``--network=none``); iptables rules are configured in the Docker image
itself.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import AsyncGenerator
from typing import Any

from beddel.domain.errors import AgentError
from beddel.domain.models import AgentResult
from beddel.error_codes import (
    AGENT_EXECUTION_FAILED,
    AGENT_STREAM_INTERRUPTED,
    CODEX_DOCKER_UNAVAILABLE,
    CODEX_EXEC_FAILED,
    CODEX_TIMEOUT,
)

__all__ = ["CodexAgentAdapter"]

_log = logging.getLogger(__name__)

_SUPPORTED_SANDBOXES = ("read-only", "workspace-write", "danger-full-access")

_DEFAULT_MODEL = "gpt-5.3-codex"
_DEFAULT_DOCKER_IMAGE = "codex-universal:latest"
_DEFAULT_TIMEOUT = 300


class CodexAgentAdapter:
    """Codex Docker-isolated agent adapter using subprocess execution.

    Implements the ``IAgentAdapter`` protocol structurally by exposing
    :meth:`execute` and :meth:`stream` with matching signatures.  All
    interaction with the Codex CLI happens through
    ``asyncio.create_subprocess_exec`` inside a Docker container.

    Args:
        model: Default model identifier for Codex invocations.  When
            ``None``, reads from ``CODEX_MODEL`` env var (default
            ``gpt-5.3-codex``).
        docker_image: Docker image to use for Codex execution.  When
            ``None``, reads from ``CODEX_DOCKER_IMAGE`` env var (default
            ``codex-universal:latest``).
        timeout: Maximum execution time in seconds before the subprocess
            is killed.  When ``None``, reads from ``CODEX_TIMEOUT`` env
            var (default ``300``).
        workspace_dir: Host directory to mount into the container as
            ``/workspace``.  When ``None``, no workspace is mounted.
    """

    def __init__(
        self,
        model: str | None = None,
        docker_image: str | None = None,
        timeout: int | None = None,
        workspace_dir: str | None = None,
    ) -> None:
        self._model = model or os.environ.get("CODEX_MODEL", _DEFAULT_MODEL)
        self._docker_image = docker_image or os.environ.get(
            "CODEX_DOCKER_IMAGE", _DEFAULT_DOCKER_IMAGE
        )
        self._timeout = timeout or int(os.environ.get("CODEX_TIMEOUT", str(_DEFAULT_TIMEOUT)))
        self._workspace_dir = workspace_dir

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_docker_command(
        self,
        prompt: str,
        *,
        model: str,
        sandbox: str,
        tools: list[str] | None,
    ) -> list[str]:
        """Build the Docker argument list for ``codex exec``.

        Args:
            prompt: The prompt text passed to ``codex exec``.
            model: Model identifier to pass via ``--model``.
            sandbox: Sandbox level controlling volume mount permissions.
            tools: Optional tool names (reserved for future use).

        Returns:
            A list of string arguments suitable for
            ``asyncio.create_subprocess_exec``.

        Raises:
            AgentError: ``BEDDEL-AGENT-701`` if ``sandbox`` is not a
                recognized value.
        """
        if sandbox not in _SUPPORTED_SANDBOXES:
            raise AgentError(
                code=AGENT_EXECUTION_FAILED,
                message=f"Unsupported sandbox value: {sandbox!r}",
                details={
                    "sandbox": sandbox,
                    "supported": list(_SUPPORTED_SANDBOXES),
                },
            )

        cmd: list[str] = ["docker", "run", "--rm"]

        # Workspace volume mount based on sandbox level
        if self._workspace_dir:
            if sandbox == "read-only":
                cmd.extend(["-v", f"{self._workspace_dir}:/workspace:ro"])
            elif sandbox == "workspace-write":
                cmd.extend(["-v", f"{self._workspace_dir}:/workspace:rw"])
            elif sandbox == "danger-full-access":
                cmd.extend(["-v", f"{self._workspace_dir}:/workspace:rw", "--privileged"])

        # Network isolation
        cmd.append("--network=none")

        # Pass through OPENAI_API_KEY from host
        cmd.extend(["--env", "OPENAI_API_KEY"])

        # Docker image
        cmd.append(self._docker_image)

        # Inner codex command
        cmd.extend(["codex", "exec", "--json", "--full-auto", "--model", model, prompt])

        return cmd

    def _parse_jsonl_events(
        self, lines: list[str]
    ) -> tuple[str, list[str], list[dict[str, Any]], dict[str, Any]]:
        """Parse JSONL event lines from ``codex exec --json`` output.

        Processes each line as a JSON object and extracts output text,
        changed file paths, structured events, and token usage.

        Args:
            lines: Raw stdout lines from the Codex subprocess.

        Returns:
            A tuple of ``(output, files_changed, events, usage)`` where:

            - ``output``: Concatenated agent message content.
            - ``files_changed``: List of file paths modified by the agent.
            - ``events``: List of raw event dicts for audit/replay.
            - ``usage``: Token usage dict with ``prompt_tokens``,
              ``completion_tokens``, and ``total_tokens``.

        Raises:
            AgentError: ``BEDDEL-CODEX-801`` if a ``turn.failed`` event
                is encountered.
        """
        output_parts: list[str] = []
        files_changed: list[str] = []
        events: list[dict[str, Any]] = []
        usage: dict[str, Any] = {}

        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue

            try:
                event = json.loads(stripped)
            except (json.JSONDecodeError, ValueError):
                _log.warning("Skipping malformed JSONL line: %.200s", stripped)
                continue

            event_type = event.get("type", "")

            if event_type == "thread.started":
                events.append(event)

            elif event_type == "item.completed":
                item = event.get("item", {})
                item_type = item.get("type", "")

                if item_type == "agent_message":
                    content = item.get("content", "")
                    if isinstance(content, str):
                        output_parts.append(content)
                    elif isinstance(content, list):
                        for part in content:
                            if isinstance(part, dict):
                                output_parts.append(part.get("text", ""))

                elif item_type == "file_change":
                    file_path = item.get("path", "")
                    if file_path:
                        files_changed.append(file_path)

            elif event_type == "turn.completed":
                turn_usage = event.get("usage", {})
                if turn_usage:
                    usage = {
                        "prompt_tokens": turn_usage.get("prompt_tokens", 0),
                        "completion_tokens": turn_usage.get("completion_tokens", 0),
                        "total_tokens": turn_usage.get("total_tokens", 0),
                    }

            elif event_type == "turn.failed":
                error_detail = event.get("error", str(event))
                raise AgentError(
                    code=CODEX_EXEC_FAILED,
                    message=f"Codex turn failed: {error_detail}",
                    details={"event": event},
                )

            else:
                _log.debug("Skipping unrecognized Codex event type: %s", event_type)

        return "".join(output_parts), files_changed, events, usage

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
        """Execute a prompt via Docker-isolated ``codex exec --json``.

        Spawns the Codex CLI inside a Docker container as an async
        subprocess, captures stdout/stderr JSONL output, and returns a
        structured :class:`AgentResult`.

        Args:
            prompt: The instruction or task to send to the agent.
            model: Optional model override.  Falls back to the adapter's
                configured model when ``None``.
            sandbox: Sandbox access level controlling Docker volume mount
                permissions.  One of ``"read-only"``,
                ``"workspace-write"``, or ``"danger-full-access"``.
            tools: Optional list of tool names (reserved for future use).
            output_schema: Optional JSON Schema dict (currently unused
                by the Codex backend).

        Returns:
            An :class:`AgentResult` with parsed JSONL output, exit code,
            events, changed files, and usage metrics.

        Raises:
            AgentError: ``BEDDEL-CODEX-802`` on timeout,
                ``BEDDEL-CODEX-803`` if Docker is not found,
                ``BEDDEL-CODEX-801`` on non-zero exit code.
        """
        model_used = model or self._model
        cmd = self._build_docker_command(prompt, model=model_used, sandbox=sandbox, tools=tools)

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            raise AgentError(
                code=CODEX_DOCKER_UNAVAILABLE,
                message="Docker binary not found — is Docker installed and in PATH?",
                details={"cmd": cmd},
            ) from exc

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(),
                timeout=self._timeout,
            )
        except TimeoutError as exc:
            proc.kill()
            await proc.wait()
            raise AgentError(
                code=CODEX_TIMEOUT,
                message=f"Codex Docker process timed out after {self._timeout}s",
                details={"timeout": self._timeout, "cmd": cmd},
            ) from exc

        stdout_text = stdout_bytes.decode("utf-8", errors="replace") if stdout_bytes else ""
        stderr_text = stderr_bytes.decode("utf-8", errors="replace") if stderr_bytes else ""

        if proc.returncode != 0:
            raise AgentError(
                code=CODEX_EXEC_FAILED,
                message=f"Codex Docker exited with code {proc.returncode}",
                details={
                    "exit_code": proc.returncode,
                    "stderr": stderr_text,
                    "cmd": cmd,
                },
            )

        stdout_lines = stdout_text.splitlines()
        output, files_changed, events, usage = self._parse_jsonl_events(stdout_lines)

        return AgentResult(
            exit_code=0,
            output=output,
            events=events,
            files_changed=files_changed,
            usage=usage,
            agent_id=f"codex-{model_used}",
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
        """Stream events from the Codex agent.

        Since the Docker subprocess does not support true streaming, this
        method calls :meth:`execute` internally and yields a single
        ``"complete"`` event with the full output.

        Args:
            prompt: The instruction or task to send to the agent.
            model: Optional model override.  Falls back to the adapter's
                configured model when ``None``.
            sandbox: Sandbox access level for the agent execution.
            tools: Optional list of tool names.

        Yields:
            A single event dict with keys ``"type"``, ``"output"``, and
            ``"exit_code"``.

        Raises:
            AgentError: ``BEDDEL-AGENT-703`` if the underlying execution
                times out (re-raised from ``BEDDEL-CODEX-802``).
        """
        try:
            result = await self.execute(prompt, model=model, sandbox=sandbox, tools=tools)
        except AgentError as exc:
            if exc.code == CODEX_TIMEOUT:
                raise AgentError(
                    code=AGENT_STREAM_INTERRUPTED,
                    message="Codex stream interrupted due to timeout",
                    details=exc.details,
                ) from exc
            raise
        yield {
            "type": "complete",
            "output": result.output,
            "exit_code": result.exit_code,
        }
