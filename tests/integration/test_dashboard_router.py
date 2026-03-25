"""Integration tests for Dashboard Server Protocol router (Story D1.3, Task 4)."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

import httpx
from fastapi import FastAPI

from beddel.domain.models import BeddelEvent, EventType, Step, Workflow
from beddel.integrations.dashboard.bridge import DashboardSSEBridge
from beddel.integrations.dashboard.history import ExecutionHistoryStore
from beddel.integrations.dashboard.inspector import WorkflowInspector
from beddel.integrations.dashboard.router import create_dashboard_router

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class MockExecutor:
    """Minimal mock executor for router tests."""

    async def execute_stream(
        self,
        workflow: Workflow,
        inputs: dict[str, Any] | None = None,
        *,
        execution_strategy: Any = None,
    ) -> AsyncGenerator[BeddelEvent, None]:
        yield BeddelEvent(event_type=EventType.WORKFLOW_START, data={"workflow_id": workflow.id})
        yield BeddelEvent(event_type=EventType.STEP_START, step_id="s1", data={"primitive": "llm"})
        yield BeddelEvent(event_type=EventType.STEP_END, step_id="s1", data={"result": "ok"})
        yield BeddelEvent(event_type=EventType.WORKFLOW_END, data={"workflow_id": workflow.id})


def _make_workflow(wf_id: str = "wf-1") -> Workflow:
    return Workflow(
        id=wf_id,
        name="Test Workflow",
        steps=[Step(id="s1", primitive="llm", config={"model": "gpt-4"})],
    )


def _make_app() -> tuple[FastAPI, ExecutionHistoryStore]:
    """Build a FastAPI app with the dashboard router mounted."""
    wf = _make_workflow()
    workflows = {wf.id: wf}
    history = ExecutionHistoryStore()
    executor = MockExecutor()
    inspector = WorkflowInspector(workflows)
    bridge = DashboardSSEBridge(executor=executor, history=history)  # type: ignore[arg-type]
    router = create_dashboard_router(
        inspector=inspector,
        bridge=bridge,
        history=history,
        workflows=workflows,
    )
    app = FastAPI()
    app.include_router(router)
    return app, history


def _parse_sse_events(text: str) -> list[dict[str, str]]:
    """Parse raw SSE text into a list of {event, data} dicts."""
    text = text.replace("\r\n", "\n")
    blocks = text.split("\n\n")
    events: list[dict[str, str]] = []
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        event_dict: dict[str, str] = {}
        data_lines: list[str] = []
        for line in block.split("\n"):
            if line.startswith("event:"):
                event_dict["event"] = line[len("event:") :].strip()
            elif line.startswith("data:"):
                data_lines.append(line[len("data:") :].strip())
        if data_lines:
            event_dict["data"] = "\n".join(data_lines)
        if event_dict:
            events.append(event_dict)
    return events


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestListWorkflows:
    """GET /api/workflows — returns JSON array of workflow summaries."""

    async def test_returns_workflow_list(self) -> None:
        app, _ = _make_app()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/workflows")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["id"] == "wf-1"
        assert data[0]["name"] == "Test Workflow"
        assert data[0]["step_count"] == 1


class TestGetWorkflow:
    """GET /api/workflows/{workflow_id} — returns detail or 404."""

    async def test_returns_workflow_detail(self) -> None:
        app, _ = _make_app()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/workflows/wf-1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "wf-1"
        assert "steps" in data

    async def test_returns_404_for_missing(self) -> None:
        app, _ = _make_app()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/workflows/nonexistent")
        assert resp.status_code == 404


class TestRunWorkflow:
    """POST /api/workflows/{workflow_id}/run — triggers execution."""

    async def test_returns_run_id_and_stream_url(self) -> None:
        app, _ = _make_app()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/api/workflows/wf-1/run", json={})
        assert resp.status_code == 200
        data = resp.json()
        assert "run_id" in data
        assert "stream_url" in data
        assert data["stream_url"].startswith("/api/workflows/wf-1/events/")

    async def test_returns_404_for_missing_workflow(self) -> None:
        app, _ = _make_app()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/api/workflows/nonexistent/run", json={})
        assert resp.status_code == 404


class TestStreamEvents:
    """GET /api/workflows/{workflow_id}/events/{exec_id} — SSE stream."""

    async def test_streams_sse_events(self) -> None:
        app, _ = _make_app()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            # First trigger a run
            run_resp = await client.post("/api/workflows/wf-1/run", json={})
            run_id = run_resp.json()["run_id"]
            # Then consume the SSE stream
            resp = await client.get(f"/api/workflows/wf-1/events/{run_id}")
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")
        events = _parse_sse_events(resp.text)
        assert len(events) >= 1
        event_types = [e.get("event") for e in events]
        assert "workflow_start" in event_types

    async def test_returns_404_for_missing_stream(self) -> None:
        app, _ = _make_app()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/workflows/wf-1/events/nonexistent")
        assert resp.status_code == 404


class TestListExecutions:
    """GET /api/executions — returns JSON array of execution summaries."""

    async def test_returns_execution_list(self) -> None:
        app, _ = _make_app()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            # Trigger a run and consume the stream to populate history
            run_resp = await client.post("/api/workflows/wf-1/run", json={})
            run_id = run_resp.json()["run_id"]
            await client.get(f"/api/workflows/wf-1/events/{run_id}")
            # Now list executions
            resp = await client.get("/api/executions")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) >= 1
        entry = data[0]
        assert "id" in entry
        assert "workflow_id" in entry
        assert "status" in entry
        assert "started_at" in entry

    async def test_returns_empty_list_initially(self) -> None:
        app, _ = _make_app()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/executions")
        assert resp.status_code == 200
        assert resp.json() == []


class TestGetExecution:
    """GET /api/executions/{exec_id} — returns full detail or 404."""

    async def test_returns_execution_detail(self) -> None:
        app, _ = _make_app()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            # Trigger and consume
            run_resp = await client.post("/api/workflows/wf-1/run", json={})
            run_id = run_resp.json()["run_id"]
            await client.get(f"/api/workflows/wf-1/events/{run_id}")
            # Get detail
            resp = await client.get(f"/api/executions/{run_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["run_id"] == run_id
        assert data["workflow_id"] == "wf-1"
        assert "events" in data

    async def test_returns_404_for_missing(self) -> None:
        app, _ = _make_app()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/executions/nonexistent")
        assert resp.status_code == 404


class TestMountable:
    """AC 6: Router is mountable via app.include_router()."""

    async def test_router_is_mountable(self) -> None:
        """Verify the router can be mounted on a fresh FastAPI app."""
        wf = _make_workflow()
        workflows = {wf.id: wf}
        history = ExecutionHistoryStore()
        executor = MockExecutor()
        inspector = WorkflowInspector(workflows)
        bridge = DashboardSSEBridge(executor=executor, history=history)  # type: ignore[arg-type]
        router = create_dashboard_router(
            inspector=inspector,
            bridge=bridge,
            history=history,
            workflows=workflows,
        )
        app = FastAPI()
        app.include_router(router)
        # Verify routes are registered
        route_paths = [r.path for r in app.routes if hasattr(r, "path")]  # type: ignore[union-attr]
        assert "/api/workflows" in route_paths
        assert "/api/executions" in route_paths
