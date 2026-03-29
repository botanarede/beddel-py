"""OpenClaw pipeline adapter — Gateway HTTP API event translation.

Maps the Gateway HTTP API single-event response format to Pipeline
Protocol SSE events.  The Gateway does not support true streaming;
each response is a single ``{"type": "complete", ...}`` event.
"""

from __future__ import annotations

import time
from typing import Any

from beddel.integrations.dashboard.pipeline.agent_adapter import AgentPipelineAdapter
from beddel.integrations.dashboard.pipeline.models import AgentPipelineEvent

__all__ = ["OpenClawPipelineAdapter"]

_OUTPUT_TRUNCATE_LIMIT = 500


class OpenClawPipelineAdapter(AgentPipelineAdapter):
    """Pipeline adapter for the OpenClaw Gateway HTTP API backend.

    Translates the Gateway's single-event response into a
    ``task_completed`` pipeline event.

    Args:
        agent_id: Unique identifier for this agent instance.
        gateway_url: Base URL of the OpenClaw Gateway for health checks.
    """

    def __init__(self, agent_id: str, gateway_url: str) -> None:
        super().__init__(agent_id=agent_id, backend="openclaw")
        self._gateway_url = gateway_url

    @property
    def gateway_url(self) -> str:
        """Return the configured Gateway URL."""
        return self._gateway_url

    def translate_stream_event(self, event: dict[str, Any]) -> AgentPipelineEvent | None:
        """Translate a Gateway HTTP API response event.

        The Gateway emits a single event per request::

            {"type": "complete", "output": "...", "exit_code": 0}

        This is mapped to a ``task_completed`` pipeline event.

        Args:
            event: Raw event dict from the Gateway stream.

        Returns:
            A ``task_completed`` pipeline event, or ``None`` if the
            event type is not ``"complete"``.
        """
        if event.get("type") != "complete":
            return None

        output = event.get("output", "")
        if isinstance(output, str):
            output = output[:_OUTPUT_TRUNCATE_LIMIT]

        return AgentPipelineEvent(
            event_type="task_completed",
            agent_id=self._agent_id,
            timestamp=time.time(),
            payload={
                "output": output,
                "exit_code": event.get("exit_code", 0),
            },
        )
