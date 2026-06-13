"""Unit tests for Agent Engine sidebar API routes.

All external dependencies (vertexai, beddel_deploy_agent_engine) are mocked —
no live GCP connection required.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

_MODULE = "beddel_serve_fastapi.agent_engine_routes"


@pytest.fixture()
def app() -> FastAPI:
    """Create a fresh FastAPI app with agent engine routes registered."""
    from beddel_serve_fastapi.agent_engine_routes import register_agent_engine_routes

    _app = FastAPI()
    register_agent_engine_routes(_app)
    return _app


@pytest.fixture()
def client(app: FastAPI) -> TestClient:
    """HTTP test client for the app."""
    return TestClient(app)


# ---------------------------------------------------------------------------
# GET /api/agent-engine/agents
# ---------------------------------------------------------------------------


class TestListAgentsEndpoint:
    """Tests for the list-agents endpoint."""

    def test_returns_503_when_kit_not_available(self, client: TestClient) -> None:
        with patch(f"{_MODULE}._AVAILABLE", False):
            resp = client.get("/api/agent-engine/agents")
        assert resp.status_code == 503
        assert "not installed" in resp.json()["error"]

    def test_returns_503_when_adc_not_configured(self, client: TestClient) -> None:
        mock_check = MagicMock(
            return_value={
                "configured": False,
                "project_id": None,
                "error": "ADC not configured. Run: gcloud auth application-default login",
            }
        )
        with (
            patch(f"{_MODULE}._AVAILABLE", True),
            patch(f"{_MODULE}._check_adc", mock_check),
        ):
            resp = client.get("/api/agent-engine/agents")
        assert resp.status_code == 503
        assert "gcloud" in resp.json()["error"]

    def test_returns_agent_list_when_configured(self, client: TestClient) -> None:
        mock_check = MagicMock(
            return_value={"configured": True, "project_id": "my-project", "error": None}
        )
        mock_vertexai = MagicMock()
        mock_engines = MagicMock()

        mock_agent = MagicMock()
        mock_agent.resource_name = "projects/p/locations/r/agents/a1"
        mock_agent.display_name = "Test Agent"
        mock_engines.list.return_value = [mock_agent]

        with (
            patch(f"{_MODULE}._AVAILABLE", True),
            patch(f"{_MODULE}._check_adc", mock_check),
            patch(f"{_MODULE}._vertexai", mock_vertexai),
            patch(f"{_MODULE}._agent_engines", mock_engines),
        ):
            resp = client.get("/api/agent-engine/agents")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["resource_name"] == "projects/p/locations/r/agents/a1"
        assert data[0]["display_name"] == "Test Agent"


# ---------------------------------------------------------------------------
# POST /api/agent-engine/chat
# ---------------------------------------------------------------------------


class TestChatEndpoint:
    """Tests for the chat/stream endpoint."""

    def test_returns_503_when_kit_not_available(self, client: TestClient) -> None:
        with patch(f"{_MODULE}._AVAILABLE", False):
            resp = client.post(
                "/api/agent-engine/chat",
                json={"resource_name": "x", "message": "hi"},
            )
        assert resp.status_code == 503

    def test_returns_503_when_adc_not_configured(self, client: TestClient) -> None:
        mock_check = MagicMock(
            return_value={"configured": False, "project_id": None, "error": "No ADC"}
        )
        with (
            patch(f"{_MODULE}._AVAILABLE", True),
            patch(f"{_MODULE}._check_adc", mock_check),
        ):
            resp = client.post(
                "/api/agent-engine/chat",
                json={"resource_name": "x", "message": "hi"},
            )
        assert resp.status_code == 503

    def test_streams_text_chunks(self, client: TestClient) -> None:
        mock_check = MagicMock(
            return_value={"configured": True, "project_id": "p1", "error": None}
        )
        mock_vertexai = MagicMock()
        mock_engines = MagicMock()

        # Build a mock remote app that simulates stream_query
        mock_remote = MagicMock()
        mock_remote.create_session.return_value = {"id": "sess-123"}

        mock_event = MagicMock()
        mock_part = MagicMock()
        mock_part.text = "Hello world"
        mock_event.content.parts = [mock_part]
        mock_remote.stream_query.return_value = [mock_event]

        mock_engines.get.return_value = mock_remote

        with (
            patch(f"{_MODULE}._AVAILABLE", True),
            patch(f"{_MODULE}._check_adc", mock_check),
            patch(f"{_MODULE}._vertexai", mock_vertexai),
            patch(f"{_MODULE}._agent_engines", mock_engines),
        ):
            resp = client.post(
                "/api/agent-engine/chat",
                json={"resource_name": "projects/p/agents/a1", "message": "Say hello"},
            )

        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")
        body = resp.text
        assert "Hello world" in body
        assert "sess-123" in body

    def test_creates_new_session_when_session_id_not_provided(self, client: TestClient) -> None:
        mock_check = MagicMock(
            return_value={"configured": True, "project_id": "p1", "error": None}
        )
        mock_vertexai = MagicMock()
        mock_engines = MagicMock()

        mock_remote = MagicMock()
        mock_remote.create_session.return_value = {"id": "new-sess-456"}

        mock_event = MagicMock()
        mock_part = MagicMock()
        mock_part.text = "response"
        mock_event.content.parts = [mock_part]
        mock_remote.stream_query.return_value = [mock_event]

        mock_engines.get.return_value = mock_remote

        with (
            patch(f"{_MODULE}._AVAILABLE", True),
            patch(f"{_MODULE}._check_adc", mock_check),
            patch(f"{_MODULE}._vertexai", mock_vertexai),
            patch(f"{_MODULE}._agent_engines", mock_engines),
        ):
            resp = client.post(
                "/api/agent-engine/chat",
                json={"resource_name": "projects/p/agents/a1", "message": "hi"},
            )

        assert resp.status_code == 200
        # Verify create_session was called (no session_id in request body)
        mock_remote.create_session.assert_called_once_with(user_id="sidebar-user")
        # Verify the new session_id appears in the done event
        assert "new-sess-456" in resp.text
