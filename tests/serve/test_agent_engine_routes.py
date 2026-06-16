"""Unit tests for beddel.serve.agent_engine routes."""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

import pytest

from beddel.serve.agent_engine import register_agent_engine_routes
from beddel.serve.agent_engine.models import AgentInfo, ChatChunk
from beddel.serve.agent_engine.ports import IAgentRuntimeAdapter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_adapter(
    agents: list[AgentInfo] | None = None,
    chat_chunks: list[ChatChunk] | None = None,
) -> IAgentRuntimeAdapter:
    """Build a mock IAgentRuntimeAdapter for testing."""
    if agents is None:
        agents = [AgentInfo(resource_name="projects/p/agents/1", display_name="Test Agent")]
    if chat_chunks is None:
        chat_chunks = [
            ChatChunk(text="Hello", session_id="sess-1"),
            ChatChunk(text=" world"),
            ChatChunk(text="", session_id="sess-1", done=True),
        ]

    adapter = MagicMock(spec=IAgentRuntimeAdapter)
    adapter.list_agents = AsyncMock(return_value=agents)

    async def _chat_gen(
        resource_name: str, message: str, *, session_id: str | None = None
    ) -> AsyncGenerator[ChatChunk, None]:
        for chunk in chat_chunks:
            yield chunk

    adapter.chat = _chat_gen
    return adapter  # type: ignore[return-value]


def _make_app(adapter: IAgentRuntimeAdapter):  # type: ignore[no-untyped-def]
    """Create a minimal FastAPI app with routes registered."""
    from fastapi import FastAPI

    app = FastAPI()
    register_agent_engine_routes(app, adapter)
    return app


# ---------------------------------------------------------------------------
# GET /api/agent-engine/agents
# ---------------------------------------------------------------------------


class TestListAgentsEndpoint:
    """Tests for GET /api/agent-engine/agents."""

    def test_returns_agent_list(self) -> None:
        """Returns a JSON list of agents from the adapter."""
        pytest.importorskip("fastapi")
        from fastapi.testclient import TestClient

        adapter = _make_mock_adapter(
            agents=[
                AgentInfo(resource_name="projects/p/agents/1", display_name="Agent One"),
                AgentInfo(resource_name="projects/p/agents/2", display_name="Agent Two"),
            ]
        )
        client = TestClient(_make_app(adapter))
        resp = client.get("/api/agent-engine/agents")

        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 2
        assert data[0] == {
            "resource_name": "projects/p/agents/1",
            "display_name": "Agent One",
        }
        assert data[1] == {
            "resource_name": "projects/p/agents/2",
            "display_name": "Agent Two",
        }

    def test_empty_agent_list(self) -> None:
        """Returns an empty list when adapter has no agents."""
        pytest.importorskip("fastapi")
        from fastapi.testclient import TestClient

        adapter = _make_mock_adapter(agents=[])
        client = TestClient(_make_app(adapter))
        resp = client.get("/api/agent-engine/agents")

        assert resp.status_code == 200
        assert resp.json() == []

    def test_adapter_error_returns_500(self) -> None:
        """Returns 500 when adapter.list_agents() raises."""
        pytest.importorskip("fastapi")
        from fastapi.testclient import TestClient

        adapter = MagicMock(spec=IAgentRuntimeAdapter)
        adapter.list_agents = AsyncMock(side_effect=RuntimeError("GCP unavailable"))
        client = TestClient(_make_app(adapter))  # type: ignore[arg-type]
        resp = client.get("/api/agent-engine/agents")

        assert resp.status_code == 500
        assert "error" in resp.json()


# ---------------------------------------------------------------------------
# POST /api/agent-engine/chat
# ---------------------------------------------------------------------------


class TestChatEndpoint:
    """Tests for POST /api/agent-engine/chat."""

    def _parse_sse(self, content: bytes) -> list[dict[str, str]]:
        """Parse raw SSE bytes into list of {event, data} dicts."""
        events = []
        current: dict[str, str] = {}
        for line in content.decode().splitlines():
            if line.startswith("event:"):
                current["event"] = line[len("event:") :].strip()
            elif line.startswith("data:"):
                current["data"] = line[len("data:") :].strip()
            elif line == "" and current:
                events.append(current)
                current = {}
        if current:
            events.append(current)
        return events

    def test_streams_text_chunk_and_done_events(self) -> None:
        """SSE response includes text_chunk events and a terminal done event."""
        pytest.importorskip("fastapi")
        from fastapi.testclient import TestClient

        adapter = _make_mock_adapter(
            chat_chunks=[
                ChatChunk(text="Hi", session_id="new-sess"),
                ChatChunk(text=" there"),
                ChatChunk(text="", session_id="new-sess", done=True),
            ]
        )
        client = TestClient(_make_app(adapter))
        resp = client.post(
            "/api/agent-engine/chat",
            json={"resource_name": "projects/p/agents/1", "message": "hello"},
        )

        assert resp.status_code == 200
        events = self._parse_sse(resp.content)
        event_types = [e["event"] for e in events]
        assert "text_chunk" in event_types
        assert "done" in event_types

    def test_done_event_carries_session_id(self) -> None:
        """The terminal 'done' SSE event data contains session_id."""
        pytest.importorskip("fastapi")
        from fastapi.testclient import TestClient

        adapter = _make_mock_adapter(
            chat_chunks=[
                ChatChunk(text="Hello", session_id="sess-42"),
                ChatChunk(text="", session_id="sess-42", done=True),
            ]
        )
        client = TestClient(_make_app(adapter))
        resp = client.post(
            "/api/agent-engine/chat",
            json={
                "resource_name": "projects/p/agents/1",
                "message": "hi",
                "session_id": "sess-42",
            },
        )

        events = self._parse_sse(resp.content)
        done_events = [e for e in events if e.get("event") == "done"]
        assert done_events, "No 'done' event in response"
        done_data = json.loads(done_events[0]["data"])
        assert done_data.get("session_id") == "sess-42"

    def test_text_chunk_data_contains_text(self) -> None:
        """Each text_chunk event data has a 'text' field."""
        pytest.importorskip("fastapi")
        from fastapi.testclient import TestClient

        adapter = _make_mock_adapter(
            chat_chunks=[
                ChatChunk(text="chunk1"),
                ChatChunk(text="chunk2"),
                ChatChunk(text="", done=True),
            ]
        )
        client = TestClient(_make_app(adapter))
        resp = client.post(
            "/api/agent-engine/chat",
            json={"resource_name": "projects/p/agents/1", "message": "test"},
        )

        events = self._parse_sse(resp.content)
        text_events = [e for e in events if e.get("event") == "text_chunk"]
        assert len(text_events) == 2
        texts = [json.loads(e["data"])["text"] for e in text_events]
        assert texts == ["chunk1", "chunk2"]


# ---------------------------------------------------------------------------
# GET /api/agent-engine/sidebar
# ---------------------------------------------------------------------------


class TestSidebarEndpoint:
    """Tests for GET /api/agent-engine/sidebar."""

    def test_returns_200_html_response(self) -> None:
        """Returns 200 with HTML content-type."""
        pytest.importorskip("fastapi")
        from fastapi.testclient import TestClient

        adapter = _make_mock_adapter()
        client = TestClient(_make_app(adapter))
        resp = client.get("/api/agent-engine/sidebar")

        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]

    def test_response_contains_sidebar_elements(self) -> None:
        """The sidebar HTML contains the toggle button and sidebar panel."""
        pytest.importorskip("fastapi")
        from fastapi.testclient import TestClient

        adapter = _make_mock_adapter()
        client = TestClient(_make_app(adapter))
        resp = client.get("/api/agent-engine/sidebar")

        content = resp.text
        assert "ae-toggle" in content
        assert "ae-sidebar" in content
        assert "ae-messages" in content

    def test_sidebar_html_file_exists(self) -> None:
        """sidebar.html exists at expected path in the package."""
        from pathlib import Path

        sidebar_path = (
            Path(__file__).resolve().parents[2]
            / "src"
            / "beddel"
            / "serve"
            / "agent_engine"
            / "static"
            / "sidebar.html"
        )
        assert sidebar_path.exists(), f"sidebar.html not found at {sidebar_path}"
        content = sidebar_path.read_text(encoding="utf-8")
        assert "<style>" in content
        assert "ae-toggle" in content


# ---------------------------------------------------------------------------
# Import safety
# ---------------------------------------------------------------------------


class TestImportSafety:
    """Module-level import safety tests."""

    def test_routes_module_importable_without_fastapi(self) -> None:
        """beddel.serve.agent_engine.routes is importable even if FastAPI not on sys.path."""
        import sys

        # Temporarily hide fastapi if installed — should still import cleanly
        fastapi_mod = sys.modules.pop("fastapi", None)
        try:
            import importlib

            import beddel.serve.agent_engine.routes as routes_mod

            importlib.reload(routes_mod)
            assert hasattr(routes_mod, "register_agent_engine_routes")
        finally:
            if fastapi_mod is not None:
                sys.modules["fastapi"] = fastapi_mod

    def test_register_agent_engine_routes_exported(self) -> None:
        """register_agent_engine_routes is exported from beddel.serve."""
        from beddel.serve import register_agent_engine_routes as fn

        assert callable(fn)
