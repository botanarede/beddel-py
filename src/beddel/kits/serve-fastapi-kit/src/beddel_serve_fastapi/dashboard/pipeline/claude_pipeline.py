"""Claude pipeline adapter — streaming event translation.

Maps Claude streaming events (``content_block_delta``, ``tool_use``,
``message_stop``) to Pipeline Protocol SSE events.
"""

from __future__ import annotations

import time
from typing import Any

from beddel.integrations.dashboard.pipeline.agent_adapter import AgentPipelineAdapter
from beddel.integrations.dashboard.pipeline.models import AgentPipelineEvent

__all__ = ["ClaudePipelineAdapter"]

_OUTPUT_TRUNCATE_LIMIT = 500

_FILE_TOOLS = frozenset(
    {
        "file_write",
        "file_read",
        "Write",
        "Edit",
        "Read",
    }
)


class ClaudePipelineAdapter(AgentPipelineAdapter):
    """Pipeline adapter for the Claude Agent SDK streaming backend.

    Translates Claude streaming events into pipeline SSE events:

    - ``content_block_delta`` → ``task_completed`` (partial output)
    - ``tool_use`` → ``agent_file_changed`` (if file-related tool)
    - ``message_stop`` → ``step_end``

    Args:
        agent_id: Unique identifier for this agent instance.
    """

    def __init__(self, agent_id: str) -> None:
        super().__init__(agent_id=agent_id, backend="claude")

    def translate_stream_event(self, event: dict[str, Any]) -> AgentPipelineEvent | None:
        """Translate a Claude streaming event.

        Args:
            event: Raw event dict from the Claude stream.

        Returns:
            A pipeline event, or ``None`` if the event should be skipped.
        """
        event_type = event.get("type", "")
        now = time.time()

        if event_type == "content_block_delta":
            delta = event.get("delta", {})
            text = delta.get("text", "") if isinstance(delta, dict) else ""
            if isinstance(text, str):
                text = text[:_OUTPUT_TRUNCATE_LIMIT]
            return AgentPipelineEvent(
                event_type="task_completed",
                agent_id=self._agent_id,
                timestamp=now,
                payload={"output": text, "partial": True},
            )

        if event_type == "tool_use":
            tool_name = event.get("name", "")
            if tool_name in _FILE_TOOLS:
                tool_input = event.get("input", {})
                file_path = tool_input.get("path", "") if isinstance(tool_input, dict) else ""
                return AgentPipelineEvent(
                    event_type="agent_file_changed",
                    agent_id=self._agent_id,
                    timestamp=now,
                    payload={"file": file_path, "tool": tool_name},
                )
            return None

        if event_type == "message_stop":
            return AgentPipelineEvent(
                event_type="step_end",
                agent_id=self._agent_id,
                timestamp=now,
                payload={},
            )

        return None
