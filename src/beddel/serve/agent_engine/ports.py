"""Port interface for the Agent Engine serve tier.

Defines :class:`IAgentRuntimeAdapter` — a delivery-tier local port that
abstracts the sidebar's interaction with a specific agent runtime backend
(e.g. Vertex AI Agent Engine).

This port lives in ``serve/agent_engine/ports.py``, NOT in
``domain/ports.py``, because the domain core (executor, resolver, registry)
never invokes it.  It is consumed exclusively by the serve-tier route
handlers (``serve/agent_engine/routes.py``) and their tests.

Implementations of this port bridge the sidebar UI to a concrete runtime
backend, handling agent discovery and streamed chat interactions with
session management.

[Source: docs/architecture/decisions/adr-0013-agent-engine-sidebar-bundled-serve-tier.md]
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Protocol, runtime_checkable

from .models import AgentInfo, ChatChunk

__all__ = ["IAgentRuntimeAdapter"]


@runtime_checkable
class IAgentRuntimeAdapter(Protocol):
    """Delivery-tier local port for agent runtime interactions.

    Defines the structural contract that concrete adapters must satisfy to
    bridge the Agent Engine sidebar to a specific runtime backend (e.g.
    Vertex AI Agent Engine, local mock, or future alternative runtimes).

    This is a **local port** — it exists solely within the serve tier and
    is never referenced by the domain core.  The dependency direction is:

        routes.py → IAgentRuntimeAdapter → (concrete adapter)

    Uses structural subtyping (``Protocol``) with ``@runtime_checkable``
    consistent with :class:`~beddel.domain.ports.IAgentAdapter` and other
    domain ports.

    Example::

        class VertexAgentEngineAdapter:
            async def list_agents(self) -> list[AgentInfo]:
                ...

            async def chat(
                self, resource_name: str, message: str, *, session_id: str | None = None
            ) -> AsyncGenerator[ChatChunk, None]:
                ...

        adapter = VertexAgentEngineAdapter()
        assert isinstance(adapter, IAgentRuntimeAdapter)
    """

    async def list_agents(self) -> list[AgentInfo]:
        """Discover available agents in the runtime.

        Queries the agent runtime backend for all deployed agents and
        returns their metadata.  Used by the sidebar to populate the
        agent selection dropdown.

        Returns:
            A list of :class:`~.models.AgentInfo` dataclasses, each
            containing the agent's ``resource_name`` and ``display_name``.
        """
        ...

    async def chat(
        self,
        resource_name: str,
        message: str,
        *,
        session_id: str | None = None,
    ) -> AsyncGenerator[ChatChunk, None]:
        """Stream a conversation with a specific agent.

        Sends a user message to the identified agent and yields structured
        :class:`~.models.ChatChunk` instances as text arrives from the
        runtime.  Manages session continuity — when ``session_id`` is
        ``None``, the adapter creates a new session and propagates the
        assigned ID in the first yielded chunk.

        Args:
            resource_name: Fully-qualified agent resource name
                (e.g. ``"projects/my-proj/locations/us-central1/agentEngines/123"``).
            message: The user's message text to send to the agent.
            session_id: Optional existing session identifier for
                conversation continuity.  When ``None``, a new session
                is created by the runtime.

        Yields:
            :class:`~.models.ChatChunk` instances carrying text content,
            optional session metadata (first chunk of new sessions), and
            a ``done`` flag on the terminal chunk.
        """
        ...  # pragma: no cover
        yield ChatChunk(text="")  # pragma: no cover
