"""OpenClaw Gateway HTTP API agent adapter.

This adapter bridges the Beddel domain core to the OpenClaw Gateway,
enabling agent-style interactions through the OpenAI-compatible
``/v1/chat/completions`` endpoint.  It implements the
:class:`~beddel.domain.ports.IAgentAdapter` protocol via structural
subtyping (no explicit inheritance).

The Gateway is expected to be running at the configured ``gateway_url``
(default: ``http://localhost:3000``).  Each request is session-isolated
(stateless).
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

import httpx

from beddel.domain.errors import AgentError
from beddel.domain.models import AgentResult
from beddel.error_codes import (
    AGENT_EXECUTION_FAILED,
    AGENT_STREAM_INTERRUPTED,
    AGENT_TIMEOUT,
)

__all__ = ["OpenClawAgentAdapter"]

_SUPPORTED_SANDBOXES = ("read-only", "workspace-write", "danger-full-access")


class OpenClawAgentAdapter:
    """OpenClaw Gateway HTTP API agent adapter.

    Implements the ``IAgentAdapter`` protocol structurally by exposing
    :meth:`execute` and :meth:`stream` with matching signatures.  All
    interaction with the OpenClaw Gateway happens through
    ``httpx.AsyncClient`` against the ``/v1/chat/completions`` endpoint.

    Args:
        gateway_url: Base URL of the OpenClaw Gateway HTTP API.
        agent: OpenClaw agent name for routing (e.g. ``"main"``,
            ``"architect"``, ``"digger"``).
        model: Default model identifier for Gateway requests.  When
            ``None``, the Gateway uses its own default.
        timeout: Maximum time in seconds to wait for a Gateway response.
    """

    def __init__(
        self,
        gateway_url: str = "http://localhost:3000",
        agent: str = "main",
        model: str | None = None,
        timeout: int = 120,
    ) -> None:
        self._gateway_url = gateway_url
        self._agent = agent
        self._model = model
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
        """Execute a prompt via the OpenClaw Gateway HTTP API.

        Sends a ``POST /v1/chat/completions`` request to the Gateway,
        parses the OpenAI-compatible response, and returns a structured
        :class:`AgentResult`.

        Args:
            prompt: The instruction or task to send to the agent.
            model: Optional model override.  Falls back to the adapter's
                configured model when ``None``.
            sandbox: Sandbox access level.  ``"read-only"`` sends the
                request without tool permissions; ``"workspace-write"``
                and ``"danger-full-access"`` include tool authorization.
            tools: Optional list of tool names in OpenAI-compatible
                format to include in the request body.
            output_schema: Optional JSON Schema dict (currently unused
                by the Gateway backend).

        Returns:
            An :class:`AgentResult` with the Gateway's response content,
            usage metrics, and execution metadata.

        Raises:
            AgentError: ``BEDDEL-AGENT-701`` on connection error or
                non-200 response, ``BEDDEL-AGENT-702`` on timeout.
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

        model_used = model or self._model
        payload = self._build_payload(
            prompt,
            model=model_used,
            sandbox=sandbox,
            tools=tools,
        )
        url = f"{self._gateway_url}/v1/chat/completions"

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(url, json=payload)
        except httpx.ConnectError as exc:
            raise AgentError(
                code=AGENT_EXECUTION_FAILED,
                message=f"Failed to connect to OpenClaw Gateway at {url}",
                details={"url": url, "agent": self._agent},
            ) from exc
        except httpx.TimeoutException as exc:
            raise AgentError(
                code=AGENT_TIMEOUT,
                message=f"OpenClaw Gateway request timed out after {self._timeout}s",
                details={"timeout": self._timeout, "url": url},
            ) from exc

        if response.status_code != 200:
            raise AgentError(
                code=AGENT_EXECUTION_FAILED,
                message=f"OpenClaw Gateway returned status {response.status_code}",
                details={
                    "status_code": response.status_code,
                    "body": response.text,
                    "url": url,
                },
            )

        data = response.json()
        content = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})

        return AgentResult(
            exit_code=0,
            output=content,
            events=[],
            files_changed=[],
            usage=usage,
            agent_id=f"openclaw-{self._agent}",
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
        """Stream events from the OpenClaw Gateway.

        Since the Gateway does not support true SSE streaming, this
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
                times out (re-raised from ``BEDDEL-AGENT-702``).

        Note:
            This adapter emits exactly one terminal event per call because
            the Gateway does not support incremental streaming.  Callers
            expecting token-level or chunk-level events should be aware
            of this limitation.
        """
        try:
            result = await self.execute(
                prompt,
                model=model,
                sandbox=sandbox,
                tools=tools,
            )
        except AgentError as exc:
            if exc.code == AGENT_TIMEOUT:
                raise AgentError(
                    code=AGENT_STREAM_INTERRUPTED,
                    message="OpenClaw Gateway stream interrupted due to timeout",
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

    def _build_payload(
        self,
        prompt: str,
        *,
        model: str | None,
        sandbox: str,
        tools: list[str] | None,
    ) -> dict[str, Any]:
        """Build the JSON request payload for ``/v1/chat/completions``.

        Args:
            prompt: The prompt text (sent as the user message).
            model: Model identifier to include in the payload.
            sandbox: Sandbox level controlling tool authorization.
            tools: Optional tool names for the request body.

        Returns:
            A dict suitable for ``httpx.AsyncClient.post(json=...)``.
        """
        agent_context = f"You are the {self._agent} agent."
        if sandbox in ("workspace-write", "danger-full-access"):
            agent_context += f" Tool authorization level: {sandbox}."

        messages: list[dict[str, str]] = [
            {"role": "system", "content": agent_context},
            {"role": "user", "content": prompt},
        ]

        payload: dict[str, Any] = {"messages": messages}
        if model is not None:
            payload["model"] = model
        if tools is not None:
            payload["tools"] = tools

        return payload
