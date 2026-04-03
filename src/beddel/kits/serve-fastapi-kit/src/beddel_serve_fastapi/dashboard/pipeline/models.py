"""Pipeline event and health status data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

__all__ = ["AgentHealthStatus", "AgentPipelineEvent"]


@dataclass
class AgentPipelineEvent:
    """A single Pipeline Protocol SSE event from an agent execution.

    Attributes:
        event_type: SSE event type (e.g. ``pipeline_stage_changed``,
            ``task_completed``, ``agent_file_changed``, ``step_end``,
            ``gate_failed``).
        agent_id: Identifier of the agent that produced this event.
        timestamp: Unix timestamp (seconds) when the event was created.
        payload: Arbitrary event-specific data.
    """

    event_type: str
    agent_id: str
    timestamp: float
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentHealthStatus:
    """Health status snapshot for a registered agent adapter.

    Attributes:
        agent_id: Identifier of the agent.
        backend: Backend name (e.g. ``openclaw``, ``claude``, ``codex``).
        status: One of ``connected``, ``disconnected``, or ``degraded``.
        last_activity: Unix timestamp of last activity, or ``None``.
    """

    agent_id: str
    backend: str
    status: str
    last_activity: float | None
