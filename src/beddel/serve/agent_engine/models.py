"""Data models for the Agent Engine serve tier.

Defines lightweight dataclasses used by :class:`IAgentRuntimeAdapter` and
downstream consumers (routes, tests).  These are delivery-tier models —
they do NOT belong in ``beddel.domain.models`` because they describe
transport/presentation concerns specific to the Agent Engine sidebar.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["AgentInfo", "ChatChunk"]


@dataclass(frozen=True)
class AgentInfo:
    """Metadata for a deployed agent available in the runtime.

    Returned by :meth:`IAgentRuntimeAdapter.list_agents` to populate
    the agent selection dropdown in the sidebar UI.

    Attributes:
        resource_name: Fully-qualified Vertex AI resource name
            (e.g. ``projects/my-proj/locations/us-central1/agentEngines/123``).
        display_name: Human-readable agent name shown in the UI.
    """

    resource_name: str
    display_name: str


@dataclass
class ChatChunk:
    """A single streaming text chunk from the agent runtime.

    Yielded by :meth:`IAgentRuntimeAdapter.chat` as an async generator.
    Carries both the text payload and session continuity metadata.

    The first chunk after a new session is created carries the
    ``session_id`` so the caller can persist it for subsequent messages.
    The final chunk in a stream has ``done=True`` to signal explicit
    stream completion.

    Attributes:
        text: The text content of this chunk.
        session_id: Session identifier propagated on the first chunk
            of a newly created session, or ``None`` for continuation chunks.
        done: Whether this is the terminal chunk in the stream.
    """

    text: str
    session_id: str | None = None
    done: bool = False
