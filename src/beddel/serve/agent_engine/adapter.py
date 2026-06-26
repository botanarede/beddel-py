"""Concrete adapter: VertexAgentEngineAdapter.

Implements :class:`~beddel.serve.agent_engine.ports.IAgentRuntimeAdapter`
using the Vertex AI new Client API (``vertexai.Client().agent_engines``).

All GCP imports are lazy — the module is safe to import when ``vertexai``
is not installed.  Construction raises :exc:`ImportError` if the package
is absent, so the caller (routes.py) can degrade gracefully to 503.

[Source: docs/architecture/decisions/adr-0013-agent-engine-sidebar-bundled-serve-tier.md]
[Source: repo/kits/serve-fastapi-kit/python/beddel_serve_fastapi/agent_engine_routes.py]
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator
from typing import Any

from .models import AgentInfo, ChatChunk

__all__ = ["VertexAgentEngineAdapter"]

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy vertexai import — module is safe to import when vertexai is absent
# ---------------------------------------------------------------------------

_AVAILABLE = False
_vertexai: Any = None

try:
    import vertexai as _vertexai

    _AVAILABLE = True
except ImportError:
    pass

_USER_ID = "sidebar-user"


class VertexAgentEngineAdapter:
    """Concrete implementation of IAgentRuntimeAdapter targeting the Vertex AI
    Agent Engine new Client API (``vertexai.Client().agent_engines``).

    The new Client API returns string chunks directly from ``stream_query()``,
    eliminating the dict-parsing required by the legacy ``agent_engines`` global.

    GCP imports are lazy — this class is safe to instantiate only when
    ``vertexai`` is available.  Callers should catch :exc:`ImportError` at
    construction time and return a 503 response.

    Example::

        try:
            adapter = VertexAgentEngineAdapter(project="my-project")
        except ImportError as exc:
            return JSONResponse(status_code=503, content={"error": str(exc)})
    """

    def __init__(self, project: str, location: str = "us-central1") -> None:
        if not _AVAILABLE:
            raise ImportError("vertexai not installed. Run: pip install google-cloud-aiplatform")
        self._project = project
        self._location = location
        self._client: Any = _vertexai.Client(project=project, location=location)

    # ------------------------------------------------------------------
    # IAgentRuntimeAdapter — list_agents
    # ------------------------------------------------------------------

    async def list_agents(self) -> list[AgentInfo]:
        """Discover available agents via ``client.agent_engines.list()``.

        Runs the synchronous SDK call in a thread-pool executor to avoid
        blocking the event loop.

        Returns:
            List of :class:`~.models.AgentInfo`, one per deployed agent.
        """
        loop = asyncio.get_event_loop()
        try:
            agents = await loop.run_in_executor(
                None, lambda: list(self._client.agent_engines.list())
            )
        except Exception as exc:
            logger.exception("Failed to list Agent Engine agents")
            raise RuntimeError(f"Failed to list agents: {exc}") from exc

        return [
            AgentInfo(
                resource_name=agent.api_resource.name,
                display_name=(
                    agent.api_resource.display_name or agent.api_resource.name.split("/")[-1]
                ),
            )
            for agent in agents
            if agent.api_resource is not None
        ]

    # ------------------------------------------------------------------
    # IAgentRuntimeAdapter — chat
    # ------------------------------------------------------------------

    async def chat(
        self,
        resource_name: str,
        message: str,
        *,
        session_id: str | None = None,
    ) -> AsyncGenerator[ChatChunk, None]:
        """Query a Vertex AI Agent Engine agent.

        Uses the synchronous ``_query`` path (httpx-based) to avoid the
        aiohttp ``max_line_length`` bug in google-genai 2.8.0 + aiohttp 3.13.

        Args:
            resource_name: Fully-qualified agent resource name.
            message: User message to send to the agent.
            session_id: Existing session ID, or ``None`` to start a new session.

        Yields:
            :class:`~.models.ChatChunk` instances.
        """
        loop = asyncio.get_event_loop()

        # Session management — create new session if needed
        if session_id is None:
            session_result: Any = await loop.run_in_executor(
                None,
                lambda: self._client.agent_engines.sessions.create(
                    name=resource_name, user_id=_USER_ID
                ),
            )
            # sessions.create returns AgentEngineSessionOperation
            if (
                hasattr(session_result, "response")
                and session_result.response
                and getattr(session_result.response, "name", None)
            ):
                session_id = session_result.response.name
            elif hasattr(session_result, "name") and session_result.name:
                session_id = session_result.name
            else:
                session_id = str(session_result)
            logger.info("Created session: %s", session_id)
            yield ChatChunk(text="", session_id=session_id)

        # Query agent via sync _query (httpx, bypasses aiohttp max_line_length bug)
        queue: asyncio.Queue[str | None] = asyncio.Queue()

        def _run_sync() -> None:
            try:
                logger.info("Querying agent %s (session=%s)", resource_name, session_id)
                response = self._client.agent_engines._query(
                    name=resource_name,
                    config={
                        "class_method": "query",
                        "input": {
                            "message": message,
                            "user_id": _USER_ID,
                            "session_id": session_id,
                        },
                    },
                )
                # Extract text from QueryReasoningEngineResponse
                text = self._extract_query_response(response)
                if text:
                    queue.put_nowait(text)
                else:
                    queue.put_nowait("[No response from agent]")
            except Exception as exc:
                logger.exception("Agent query failed: %s", exc)
                queue.put_nowait(f"[Agent error: {exc}]")
            finally:
                queue.put_nowait(None)  # sentinel

        loop.run_in_executor(None, _run_sync)
        await asyncio.sleep(0.01)  # let executor start

        while True:
            chunk_str = await queue.get()
            if chunk_str is None:
                break
            yield ChatChunk(text=chunk_str)

        # Terminal chunk
        yield ChatChunk(text="", session_id=session_id, done=True)

    @staticmethod
    def _extract_query_response(response: Any) -> str:
        """Extract displayable text from a _query response.

        The response may be a QueryReasoningEngineResponse, dict, or string.
        """
        if isinstance(response, str):
            return response
        if hasattr(response, "output"):
            return str(response.output)
        if hasattr(response, "body"):
            # SdkHttpResponse — parse the JSON body
            import json

            try:
                body = (
                    json.loads(response.body) if isinstance(response.body, str) else response.body
                )
                return str(body.get("output", body.get("text", body)))
            except (json.JSONDecodeError, AttributeError, TypeError):
                return str(response.body)
        if isinstance(response, dict):
            return str(response.get("output", response.get("text", str(response))))
        return str(response)
