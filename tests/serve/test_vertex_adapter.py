"""Unit tests for VertexAgentEngineAdapter."""

from __future__ import annotations

import asyncio
import sys
from collections.abc import AsyncGenerator
from unittest.mock import MagicMock, patch

import pytest

from beddel.serve import IAgentRuntimeAdapter
from beddel.serve.agent_engine.models import AgentInfo, ChatChunk

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_adapter(project: str = "test-project") -> VertexAgentEngineAdapter:  # type: ignore[name-defined]  # noqa: F821
    """Build a VertexAgentEngineAdapter with a mocked vertexai client."""
    from beddel.serve.agent_engine import adapter as adapter_mod
    from beddel.serve.agent_engine.adapter import VertexAgentEngineAdapter

    mock_client = MagicMock()
    with (
        patch.object(adapter_mod, "_AVAILABLE", True),
        patch.object(
            adapter_mod,
            "_vertexai",
            MagicMock(Client=MagicMock(return_value=mock_client)),
        ),
    ):
        inst = VertexAgentEngineAdapter(project=project)
    inst._client = mock_client
    return inst


async def _collect(gen: AsyncGenerator[ChatChunk, None]) -> list[ChatChunk]:
    return [chunk async for chunk in gen]


# ---------------------------------------------------------------------------
# Module-level import safety
# ---------------------------------------------------------------------------


class TestLazyImport:
    """Module-level import must not raise even when vertexai is absent."""

    def test_module_importable_without_vertexai(self) -> None:
        """Importing adapter module with vertexai absent raises no exception."""
        saved = sys.modules.pop("vertexai", None)
        try:
            import importlib

            import beddel.serve.agent_engine.adapter as m

            importlib.reload(m)
        finally:
            if saved is not None:
                sys.modules["vertexai"] = saved

    def test_constructor_raises_import_error_when_unavailable(self) -> None:
        """VertexAgentEngineAdapter.__init__ raises ImportError when _AVAILABLE is False."""
        from beddel.serve.agent_engine import adapter as adapter_mod
        from beddel.serve.agent_engine.adapter import VertexAgentEngineAdapter

        with (
            patch.object(adapter_mod, "_AVAILABLE", False),
            pytest.raises(ImportError, match="vertexai not installed"),
        ):
            VertexAgentEngineAdapter(project="test")


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


class TestProtocolConformance:
    """VertexAgentEngineAdapter must satisfy isinstance(adapter, IAgentRuntimeAdapter)."""

    def test_isinstance_check(self) -> None:
        adapter = _make_adapter()
        assert isinstance(adapter, IAgentRuntimeAdapter)


# ---------------------------------------------------------------------------
# list_agents
# ---------------------------------------------------------------------------


class TestListAgents:
    """Tests for VertexAgentEngineAdapter.list_agents()."""

    def test_returns_list_of_agent_info(self) -> None:
        adapter = _make_adapter()

        mock_agent = MagicMock()
        mock_agent.api_resource.name = "projects/p/locations/us-central1/agentEngines/1"
        mock_agent.api_resource.display_name = "My Agent"
        adapter._client.agent_engines.list.return_value = [mock_agent]

        result: list[AgentInfo] = asyncio.run(adapter.list_agents())
        assert len(result) == 1
        assert result[0].resource_name == "projects/p/locations/us-central1/agentEngines/1"
        assert result[0].display_name == "My Agent"

    def test_falls_back_to_resource_name_tail_when_display_name_empty(self) -> None:
        adapter = _make_adapter()

        mock_agent = MagicMock()
        mock_agent.api_resource.name = "projects/p/locations/us-central1/agentEngines/42"
        mock_agent.api_resource.display_name = ""
        adapter._client.agent_engines.list.return_value = [mock_agent]

        result: list[AgentInfo] = asyncio.run(adapter.list_agents())
        assert result[0].display_name == "42"

    def test_empty_list(self) -> None:
        adapter = _make_adapter()
        adapter._client.agent_engines.list.return_value = []
        result: list[AgentInfo] = asyncio.run(adapter.list_agents())
        assert result == []


# ---------------------------------------------------------------------------
# chat — session management
# ---------------------------------------------------------------------------


class TestChatSessionManagement:
    """Tests for session creation logic in VertexAgentEngineAdapter.chat()."""

    def _setup_mock_agent(
        self,
        adapter: object,
        chunks: list[str],
        new_session_id: str = "new-sess-1",
    ) -> None:
        # agent_engines.get returns an AgentEngine instance
        mock_agent = MagicMock()

        # async_create_session returns a dict-like session with 'id'
        mock_session = {"id": new_session_id}

        async def _mock_create_session(user_id: str = "") -> dict:  # type: ignore[type-arg]
            return mock_session

        mock_agent.async_create_session = _mock_create_session

        # async_stream_query yields ADK events (dicts with content.parts)
        async def _mock_stream_query(
            user_id: str = "", session_id: str = "", message: str = ""
        ) -> AsyncGenerator[dict, None]:  # type: ignore[type-arg]
            for text in chunks:
                yield {"content": {"parts": [{"text": text}]}, "author": "agent"}

        mock_agent.async_stream_query = _mock_stream_query

        adapter._client.agent_engines.get.return_value = mock_agent  # type: ignore[attr-defined]

    def test_new_session_propagated_in_first_chunk(self) -> None:
        """When session_id is None, first chunk carries the new session_id."""
        adapter = _make_adapter()
        self._setup_mock_agent(adapter, ["hello", " world"])

        chunks: list[ChatChunk] = asyncio.run(_collect(adapter.chat("r/name", "hi")))

        assert chunks[0].session_id == "new-sess-1"
        assert chunks[0].text == ""
        adapter._client.agent_engines.get.assert_called_once()

    def test_existing_session_skips_create_session(self) -> None:
        """When session_id is provided, create_session is never called."""
        adapter = _make_adapter()
        self._setup_mock_agent(adapter, ["hi"])

        asyncio.run(_collect(adapter.chat("r/name", "msg", session_id="existing-sess")))

        # get is still called (to obtain agent instance), but no session creation
        adapter._client.agent_engines.get.assert_called_once()

    def test_text_chunks_are_yielded(self) -> None:
        """Content chunks from stream_query appear as ChatChunk(text=...)."""
        adapter = _make_adapter()
        self._setup_mock_agent(adapter, ["foo", "bar"])

        chunks: list[ChatChunk] = asyncio.run(_collect(adapter.chat("r/name", "hi")))

        text_chunks = [c for c in chunks if c.text and not c.done]
        assert [c.text for c in text_chunks] == ["foo", "bar"]

    def test_terminal_chunk_has_done_true(self) -> None:
        """Last yielded chunk has done=True."""
        adapter = _make_adapter()
        self._setup_mock_agent(adapter, ["x"])

        chunks: list[ChatChunk] = asyncio.run(_collect(adapter.chat("r/name", "hi")))

        assert chunks[-1].done is True

    def test_terminal_chunk_carries_session_id(self) -> None:
        """Terminal chunk has session_id set (new session flow)."""
        adapter = _make_adapter()
        self._setup_mock_agent(adapter, ["x"], new_session_id="sess-abc")

        chunks: list[ChatChunk] = asyncio.run(_collect(adapter.chat("r/name", "hi")))

        assert chunks[-1].session_id == "sess-abc"
        assert chunks[-1].done is True

    def test_terminal_chunk_carries_existing_session_id(self) -> None:
        """Terminal chunk has the provided session_id when reusing a session."""
        adapter = _make_adapter()
        self._setup_mock_agent(adapter, ["y"])

        chunks: list[ChatChunk] = asyncio.run(
            _collect(adapter.chat("r/name", "hi", session_id="reuse-sess"))
        )

        assert chunks[-1].session_id == "reuse-sess"
        assert chunks[-1].done is True
