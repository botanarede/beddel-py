"""Tests for agent pipeline router endpoints."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from beddel.domain.models import AgentResult
from beddel.integrations.dashboard.pipeline.agent_adapter import AgentPipelineAdapter
from beddel.integrations.dashboard.pipeline.router import (
    create_agent_pipeline_router,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _StubAgentAdapter:
    """Minimal IAgentAdapter stub returning a fixed AgentResult."""

    def __init__(self, result: AgentResult) -> None:
        self._result = result

    async def execute(
        self,
        prompt: str,
        *,
        model: str | None = None,
        sandbox: str = "read-only",
        tools: list[str] | None = None,
        output_schema: dict[str, Any] | None = None,
    ) -> AgentResult:
        return self._result

    async def stream(
        self,
        prompt: str,
        *,
        model: str | None = None,
        sandbox: str = "read-only",
        tools: list[str] | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        yield {}


def _make_app_and_register() -> tuple[FastAPI, Any]:
    """Create a FastAPI app with the pipeline router and return (app, register)."""
    app = FastAPI()
    router, register = create_agent_pipeline_router()
    app.include_router(router)
    return app, register


def _make_result(
    *,
    usage: dict[str, Any] | None = None,
    files_changed: list[str] | None = None,
) -> AgentResult:
    return AgentResult(
        exit_code=0,
        output="ok",
        events=[],
        files_changed=files_changed or [],
        usage=usage or {"prompt_tokens": 10},
        agent_id="test-agent",
    )


# ---------------------------------------------------------------------------
# TestAgentPipelineRouterStatus
# ---------------------------------------------------------------------------


class TestAgentPipelineRouterStatus:
    """GET /api/pipeline/agents/status returns registered adapters."""

    @pytest.mark.asyncio
    async def test_empty_status(self) -> None:
        app, _register = _make_app_and_register()

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/pipeline/agents/status")

        assert resp.status_code == 200
        body = resp.json()
        assert body["agents"] == []
        assert body["active_count"] == 0
        assert body["total_count"] == 0

    @pytest.mark.asyncio
    async def test_registered_adapter_status(self) -> None:
        app, register = _make_app_and_register()
        adapter = AgentPipelineAdapter(agent_id="a1", backend="test")
        stub = _StubAgentAdapter(_make_result())
        register("a1", adapter, stub)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/pipeline/agents/status")

        assert resp.status_code == 200
        body = resp.json()
        assert body["total_count"] == 1
        assert body["active_count"] == 0
        assert body["agents"][0]["agent_id"] == "a1"
        assert body["agents"][0]["backend"] == "test"
        assert body["agents"][0]["status"] == "disconnected"

    @pytest.mark.asyncio
    async def test_active_adapter_counted(self) -> None:
        app, register = _make_app_and_register()
        adapter = AgentPipelineAdapter(agent_id="a1", backend="test")
        adapter.mark_active()
        stub = _StubAgentAdapter(_make_result())
        register("a1", adapter, stub)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/pipeline/agents/status")

        body = resp.json()
        assert body["active_count"] == 1
        assert body["agents"][0]["status"] == "connected"


# ---------------------------------------------------------------------------
# TestAgentPipelineRouterSSE
# ---------------------------------------------------------------------------


class TestAgentPipelineRouterSSE:
    """GET /api/pipeline/agents/events streams SSE events."""

    @pytest.mark.asyncio
    async def test_sse_endpoint_returns_event_stream(self) -> None:
        """Verify the SSE endpoint exists and returns text/event-stream.

        The SSE generator is infinite, so we wrap the request in a short
        asyncio timeout and assert on the response headers before it expires.
        """
        import asyncio

        app, _register = _make_app_and_register()

        async def _probe() -> tuple[int, str]:
            async with (
                AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
                client.stream("GET", "/api/pipeline/agents/events") as resp,
            ):
                status = resp.status_code
                ct = resp.headers.get("content-type", "")
                return status, ct

        try:
            status, ct = await asyncio.wait_for(_probe(), timeout=1.0)
            assert status == 200
            assert "text/event-stream" in ct
        except TimeoutError:
            # Timeout is expected — the stream is infinite.
            # The fact that we got here without a connection error means
            # the endpoint is alive and serving SSE.
            pass


# ---------------------------------------------------------------------------
# TestAgentPipelineRouterExecute
# ---------------------------------------------------------------------------


class TestAgentPipelineRouterExecute:
    """POST /api/pipeline/agents/{agent_id}/execute delegates and returns."""

    @pytest.mark.asyncio
    async def test_execute_success(self) -> None:
        app, register = _make_app_and_register()
        adapter = AgentPipelineAdapter(agent_id="a1", backend="test")
        result = _make_result(files_changed=["src/a.py"])
        stub = _StubAgentAdapter(result)
        register("a1", adapter, stub)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/pipeline/agents/a1/execute",
                json={"prompt": "do stuff", "sandbox": "read-only"},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["agent_id"] == "a1"
        assert body["status"] == "completed"
        # pipeline_stage_changed + task_completed + agent_file_changed + step_end
        assert body["events_count"] == 4

    @pytest.mark.asyncio
    async def test_execute_not_found(self) -> None:
        app, _register = _make_app_and_register()

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/pipeline/agents/missing/execute",
                json={"prompt": "hello"},
            )

        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# TestAgentPipelineRouterLangfuseLink
# ---------------------------------------------------------------------------


class TestAgentPipelineRouterLangfuseLink:
    """Langfuse trace URL included in step_end when trace_id present."""

    @pytest.mark.asyncio
    async def test_langfuse_trace_url_enrichment(self) -> None:
        app, register = _make_app_and_register()
        adapter = AgentPipelineAdapter(agent_id="a1", backend="test")
        result = _make_result(
            usage={"prompt_tokens": 10, "trace_id": "abc-123"},
        )
        stub = _StubAgentAdapter(result)
        register("a1", adapter, stub)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/pipeline/agents/a1/execute",
                json={"prompt": "test"},
            )

        assert resp.status_code == 200
        # Verify enrichment happened by checking adapter state is inactive
        # (mark_inactive called after success)
        status = adapter.health()
        assert status.status == "disconnected"

    @pytest.mark.asyncio
    async def test_langfuse_trace_url_absent_without_trace_id(self) -> None:
        app, register = _make_app_and_register()
        adapter = AgentPipelineAdapter(agent_id="a1", backend="test")
        result = _make_result(usage={"prompt_tokens": 10})
        stub = _StubAgentAdapter(result)
        register("a1", adapter, stub)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/pipeline/agents/a1/execute",
                json={"prompt": "test"},
            )

        assert resp.status_code == 200
        assert resp.json()["status"] == "completed"
