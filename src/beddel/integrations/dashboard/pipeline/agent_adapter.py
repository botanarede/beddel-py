"""Base agent pipeline adapter — translates domain events to SSE events.

Provides :class:`AgentPipelineAdapter`, a concrete base class that
backend-specific adapters (OpenClaw, Claude, Codex) inherit from.
The base class handles the common event mapping defined in AC 3:

- Agent execution started → ``pipeline_stage_changed``
- Agent message/output → ``task_completed``
- File change → ``agent_file_changed``
- Execution completed → ``step_end`` with usage data
- Execution failed → ``gate_failed``
"""

from __future__ import annotations

import time
from typing import Any

from beddel.domain.errors import AgentError
from beddel.domain.models import AgentResult
from beddel.integrations.dashboard.pipeline.models import (
    AgentHealthStatus,
    AgentPipelineEvent,
)

__all__ = ["AgentPipelineAdapter"]

_OUTPUT_TRUNCATE_LIMIT = 500


class AgentPipelineAdapter:
    """Base adapter translating :class:`AgentResult` into pipeline SSE events.

    Concrete base class — backend-specific adapters inherit and may override
    :meth:`translate_stream_event` for streaming event translation.

    Args:
        agent_id: Unique identifier for this agent instance.
        backend: Backend name (e.g. ``openclaw``, ``claude``, ``codex``).
    """

    def __init__(self, agent_id: str, backend: str) -> None:
        self._agent_id = agent_id
        self._backend = backend
        self._last_activity: float | None = None
        self._active: bool = False

    def translate_result(self, result: AgentResult) -> list[AgentPipelineEvent]:
        """Translate an :class:`AgentResult` into pipeline SSE events.

        Produces the common event sequence (AC 3):

        1. ``pipeline_stage_changed`` — execution started
        2. ``task_completed`` — agent output (truncated to 500 chars)
        3. ``agent_file_changed`` — one per file in ``files_changed``
        4. ``step_end`` — usage data and exit code

        Args:
            result: The agent execution result to translate.

        Returns:
            Ordered list of pipeline events.
        """
        now = time.time()
        events: list[AgentPipelineEvent] = [
            AgentPipelineEvent(
                event_type="pipeline_stage_changed",
                agent_id=self._agent_id,
                timestamp=now,
                payload={
                    "stage": "agent_execution",
                    "backend": self._backend,
                },
            ),
            AgentPipelineEvent(
                event_type="task_completed",
                agent_id=self._agent_id,
                timestamp=now,
                payload={
                    "output": result.output[:_OUTPUT_TRUNCATE_LIMIT],
                    "exit_code": result.exit_code,
                },
            ),
        ]
        for f in result.files_changed:
            events.append(
                AgentPipelineEvent(
                    event_type="agent_file_changed",
                    agent_id=self._agent_id,
                    timestamp=now,
                    payload={"file": f},
                ),
            )
        events.append(
            AgentPipelineEvent(
                event_type="step_end",
                agent_id=self._agent_id,
                timestamp=now,
                payload={
                    "usage": result.usage,
                    "exit_code": result.exit_code,
                },
            ),
        )
        return events

    def translate_error(self, error: AgentError) -> AgentPipelineEvent:
        """Translate an :class:`AgentError` into a ``gate_failed`` event.

        Args:
            error: The agent error to translate.

        Returns:
            A single ``gate_failed`` pipeline event.
        """
        return AgentPipelineEvent(
            event_type="gate_failed",
            agent_id=self._agent_id,
            timestamp=time.time(),
            payload={
                "code": error.code,
                "message": error.message,
                "details": error.details,
            },
        )

    def health(self) -> AgentHealthStatus:
        """Return current health status of this adapter.

        Returns:
            An :class:`AgentHealthStatus` snapshot.
        """
        status = "connected" if self._active else "disconnected"
        return AgentHealthStatus(
            agent_id=self._agent_id,
            backend=self._backend,
            status=status,
            last_activity=self._last_activity,
        )

    def mark_active(self) -> None:
        """Mark this adapter as active and update last activity timestamp."""
        self._active = True
        self._last_activity = time.time()

    def mark_inactive(self) -> None:
        """Mark this adapter as inactive and update last activity timestamp."""
        self._active = False
        self._last_activity = time.time()

    def translate_stream_event(self, event: dict[str, Any]) -> AgentPipelineEvent | None:
        """Translate a single backend-specific streaming event.

        Override in backend-specific subclasses. The base implementation
        returns ``None`` (no translation).

        Args:
            event: Raw event dict from the backend stream.

        Returns:
            A pipeline event, or ``None`` if the event should be skipped.
        """
        return None
