"""Codex pipeline adapter — JSONL event translation.

Maps Codex JSONL events (``thread.started``, ``item.completed``,
``turn.completed``) to Pipeline Protocol SSE events.
"""

from __future__ import annotations

import time
from typing import Any

from beddel.integrations.dashboard.pipeline.agent_adapter import AgentPipelineAdapter
from beddel.integrations.dashboard.pipeline.models import AgentPipelineEvent

__all__ = ["CodexPipelineAdapter"]

_OUTPUT_TRUNCATE_LIMIT = 500


class CodexPipelineAdapter(AgentPipelineAdapter):
    """Pipeline adapter for the Codex JSONL streaming backend.

    Translates Codex JSONL events into pipeline SSE events:

    - ``thread.started`` → ``pipeline_stage_changed``
    - ``item.completed`` → ``task_completed``
    - ``turn.completed`` → ``step_end``

    Args:
        agent_id: Unique identifier for this agent instance.
    """

    def __init__(self, agent_id: str) -> None:
        super().__init__(agent_id=agent_id, backend="codex")

    def translate_stream_event(self, event: dict[str, Any]) -> AgentPipelineEvent | None:
        """Translate a Codex JSONL event.

        Args:
            event: Raw event dict from the Codex JSONL stream.

        Returns:
            A pipeline event, or ``None`` if the event should be skipped.
        """
        event_type = event.get("type", "")
        now = time.time()

        if event_type == "thread.started":
            return AgentPipelineEvent(
                event_type="pipeline_stage_changed",
                agent_id=self._agent_id,
                timestamp=now,
                payload={
                    "stage": "agent_execution",
                    "backend": self._backend,
                },
            )

        if event_type == "item.completed":
            output_items = event.get("output", [])
            text_parts: list[str] = []
            if isinstance(output_items, list):
                for item in output_items:
                    if isinstance(item, dict):
                        text_parts.append(item.get("text", ""))
                    elif isinstance(item, str):
                        text_parts.append(item)
            output = "".join(text_parts)[:_OUTPUT_TRUNCATE_LIMIT]
            return AgentPipelineEvent(
                event_type="task_completed",
                agent_id=self._agent_id,
                timestamp=now,
                payload={"output": output},
            )

        if event_type == "turn.completed":
            usage = event.get("usage", {})
            return AgentPipelineEvent(
                event_type="step_end",
                agent_id=self._agent_id,
                timestamp=now,
                payload={"usage": usage if isinstance(usage, dict) else {}},
            )

        return None
