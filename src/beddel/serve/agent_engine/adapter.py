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

    # Monkey-patch aiohttp.StreamReader.readline to accept max_line_length kwarg.
    # Required because google-genai 2.8.0 passes max_line_length= but aiohttp 3.13+
    # removed it. This is a temporary workaround until google-genai is fixed upstream.
    try:
        import aiohttp

        _orig_readline = aiohttp.StreamReader.readline

        async def _patched_readline(self: Any, **kwargs: Any) -> bytes:  # type: ignore[no-untyped-def]
            kwargs.pop("max_line_length", None)
            return await _orig_readline(self)

        aiohttp.StreamReader.readline = _patched_readline  # type: ignore[assignment]
        logger.debug("Patched aiohttp.StreamReader.readline for google-genai compat")
    except (ImportError, AttributeError):
        pass

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

        Uses the agent's ``async_stream_query`` method (ADK pattern) running
        inside ``asyncio.run()`` in a thread-pool executor. The aiohttp
        ``max_line_length`` bug is patched at module level.

        Args:
            resource_name: Fully-qualified agent resource name.
            message: User message to send to the agent.
            session_id: Existing session ID, or ``None`` to start a new session.

        Yields:
            :class:`~.models.ChatChunk` instances.
        """
        loop = asyncio.get_event_loop()

        # Get the agent instance (has async_stream_query, async_create_session)
        agent: Any = await loop.run_in_executor(
            None,
            lambda: self._client.agent_engines.get(name=resource_name),
        )

        # Session management — create new session if needed
        if session_id is None:

            async def _create_session() -> Any:
                return await agent.async_create_session(user_id=_USER_ID)

            session_result: Any = await loop.run_in_executor(
                None, lambda: asyncio.run(_create_session())
            )
            # ADK session result may be dict with "id" or object with .name/.id
            if isinstance(session_result, dict):
                session_id = session_result.get("id", str(session_result))
            elif hasattr(session_result, "id"):
                session_id = session_result.id
            elif hasattr(session_result, "name"):
                session_id = session_result.name
            else:
                session_id = str(session_result)
            logger.info("Created session: %s", session_id)
            yield ChatChunk(text="", session_id=session_id)

        # Query via async_stream_query in a separate event loop (executor thread)
        queue: asyncio.Queue[str | None] = asyncio.Queue()

        def _run_sync() -> None:
            try:
                logger.info("Querying agent %s (session=%s)", resource_name, session_id)

                async def _stream() -> None:
                    chunks_received = 0
                    try:
                        async for event in agent.async_stream_query(
                            user_id=_USER_ID,
                            session_id=session_id,
                            message=message,
                        ):
                            chunks_received += 1
                            text = self._extract_text_from_event(event)
                            if text:
                                queue.put_nowait(text)
                    except Exception as stream_err:
                        logger.warning("async_stream_query failed: %s", stream_err)
                        if chunks_received == 0:
                            queue.put_nowait(f"[Agent error: {stream_err}]")

                asyncio.run(_stream())
            except Exception as exc:
                logger.exception("Error during agent query")
                queue.put_nowait(f"[Error: {exc}]")
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
    def _extract_text_from_event(event: Any) -> str:
        """Extract displayable text from an ADK stream event.

        ADK events are typically dicts with 'content.parts' structure.
        """
        if isinstance(event, str):
            return event
        if isinstance(event, dict):
            content = event.get("content", {})
            parts = content.get("parts", []) if isinstance(content, dict) else []
            texts = []
            for part in parts:
                if isinstance(part, dict) and "text" in part:
                    texts.append(part["text"])
            return "".join(texts)
        if hasattr(event, "text"):
            return str(event.text)
        return ""
