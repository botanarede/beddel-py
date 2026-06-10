"""Integration tests for AG-UI endpoint mounting via ``connect dev`` (Story BC3.2, updated BC6.3).

Tests the combined FastAPI app that mimics the ``beddel connect dev``
flow: per-workflow SSE handlers at ``/workflows/{id}`` alongside AG-UI
endpoints at ``/ag-ui/{id}``, with CORS middleware covering both.

Uses ``httpx.AsyncClient`` with ``ASGITransport`` — no real server needed.

AC #1: ``connect dev`` mounts AG-UI endpoints under ``/ag-ui/{workflow_id}``.
AC #2: Existing per-workflow SSE endpoints remain functional.
AC #3: CORS middleware covers AG-UI endpoints.
AC #5: CLI output includes AG-UI mount lines.
AC #6: All 4 validation gates pass.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from beddel_ag_ui.endpoint import create_agui_endpoint
from beddel_serve_fastapi.handler import create_beddel_handler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from beddel.domain.models import BeddelEvent, EventType, Step, Workflow

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_WORKFLOW_ID = "simple-llm"


def _make_workflow() -> Workflow:
    """Create a minimal single-step workflow matching the fixture pattern."""
    return Workflow(
        id=_WORKFLOW_ID,
        name="Simple LLM Workflow",
        steps=[Step(id="generate", primitive="llm")],
    )


async def _mock_event_stream(
    *events: BeddelEvent,
) -> AsyncGenerator[BeddelEvent, None]:
    """Yield BeddelEvent instances as an async generator."""
    for event in events:
        yield event


def _standard_events() -> tuple[BeddelEvent, ...]:
    """Return a standard set of BeddelEvents for mocking."""
    return (
        BeddelEvent(event_type=EventType.WORKFLOW_START, data={}),
        BeddelEvent(event_type=EventType.STEP_START, step_id="generate", data={}),
        BeddelEvent(
            event_type=EventType.TEXT_CHUNK,
            step_id="generate",
            data={"text": "hello"},
        ),
        BeddelEvent(event_type=EventType.STEP_END, step_id="generate", data={}),
        BeddelEvent(event_type=EventType.WORKFLOW_END, data={}),
    )


def _build_combined_app() -> FastAPI:
    """Build a FastAPI app mimicking ``connect dev``.

    Mounts:
    - CORSMiddleware with ``allow_origins=["http://localhost:3000"]``
    - Per-workflow handler at ``/workflows/{workflow_id}``
    - AG-UI endpoint at ``/ag-ui/{workflow_id}``

    Both endpoint factories have their ``WorkflowExecutor`` patched to
    return a canned event stream, avoiding real LLM calls.
    """
    app = FastAPI(title="Beddel")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    workflow = _make_workflow()

    # Patch WorkflowExecutor for the per-workflow handler
    with patch("beddel_serve_fastapi.handler.WorkflowExecutor") as mock_cls:
        mock_executor = MagicMock()
        mock_executor.execute_stream = MagicMock(
            return_value=_mock_event_stream(*_standard_events()),
        )
        mock_executor.execute = AsyncMock(
            return_value={
                "step_results": {"generate": {"content": "hello"}},
                "metadata": {},
            }
        )
        mock_cls.return_value = mock_executor
        per_wf_router = create_beddel_handler(workflow)

    # Patch WorkflowExecutor for the AG-UI endpoint
    with patch("beddel_ag_ui.endpoint.WorkflowExecutor") as mock_cls:
        mock_executor = MagicMock()
        mock_executor.execute_stream = MagicMock(
            return_value=_mock_event_stream(*_standard_events()),
        )
        mock_cls.return_value = mock_executor
        agui_router = create_agui_endpoint(workflow)

    app.include_router(per_wf_router, prefix=f"/workflows/{workflow.id}")
    app.include_router(agui_router, prefix=f"/ag-ui/{workflow.id}")

    return app


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
# AG-UI endpoint mounting (subtask 4.2) — AC #1
# ---------------------------------------------------------------------------


class TestAGUIEndpointMount:
    """Verify AG-UI endpoint is mounted and returns SSE at ``/ag-ui/{id}``."""

    @pytest.mark.asyncio
    async def test_agui_endpoint_returns_sse_stream(self) -> None:
        """POST /ag-ui/{workflow_id}/ returns text/event-stream.

        Verifies AC #1: AG-UI endpoints are mounted under /ag-ui/{workflow_id}.
        """
        with patch("beddel_ag_ui.endpoint.WorkflowExecutor") as mock_cls:
            mock_executor = MagicMock()
            mock_executor.execute_stream = MagicMock(
                return_value=_mock_event_stream(*_standard_events()),
            )
            mock_cls.return_value = mock_executor

            app = FastAPI()
            workflow = _make_workflow()
            agui_router = create_agui_endpoint(workflow)
            app.include_router(agui_router, prefix=f"/ag-ui/{workflow.id}")

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            response = await client.post(
                f"/ag-ui/{_WORKFLOW_ID}/",
                json={"topic": "testing"},
            )

        assert response.status_code == 200
        content_type = response.headers.get("content-type", "")
        assert "text/event-stream" in content_type

        events = _parse_sse_events(response.text)
        event_types = [e["event"] for e in events if "event" in e]
        assert "RUN_STARTED" in event_types
        assert "RUN_FINISHED" in event_types


# ---------------------------------------------------------------------------
# Coexistence with per-workflow endpoint (subtask 4.3) — AC #2
# ---------------------------------------------------------------------------


class TestEndpointCoexistence:
    """Verify both endpoint types work on the same FastAPI app."""

    @pytest.mark.asyncio
    async def test_per_workflow_endpoint_works_alongside_agui(self) -> None:
        """POST /workflows/{id}/ returns SSE when AG-UI is also mounted.

        Verifies AC #2: existing per-workflow SSE endpoints remain functional.
        """
        workflow = _make_workflow()

        with patch("beddel_serve_fastapi.handler.WorkflowExecutor") as mock_cls:
            mock_executor = MagicMock()
            mock_executor.execute_stream = MagicMock(
                return_value=_mock_event_stream(*_standard_events()),
            )
            mock_executor.execute = AsyncMock(
                return_value={
                    "step_results": {"generate": {"content": "hello"}},
                    "metadata": {},
                }
            )
            mock_cls.return_value = mock_executor
            per_wf_router = create_beddel_handler(workflow)

        with patch("beddel_ag_ui.endpoint.WorkflowExecutor") as mock_cls:
            mock_executor = MagicMock()
            mock_executor.execute_stream = MagicMock(
                return_value=_mock_event_stream(*_standard_events()),
            )
            mock_cls.return_value = mock_executor
            agui_router = create_agui_endpoint(workflow)

        app = FastAPI()
        app.include_router(per_wf_router, prefix=f"/workflows/{workflow.id}")
        app.include_router(agui_router, prefix=f"/ag-ui/{workflow.id}")

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            response = await client.post(
                f"/workflows/{_WORKFLOW_ID}/",
                json={"topic": "testing"},
            )

        assert response.status_code == 200
        content_type = response.headers.get("content-type", "")
        assert "text/event-stream" in content_type

        events = _parse_sse_events(response.text)
        event_types = [e["event"] for e in events if "event" in e]
        # Per-workflow handler uses Beddel event types (snake_case)
        assert "workflow_start" in event_types
        assert "workflow_end" in event_types

    @pytest.mark.asyncio
    async def test_both_endpoints_respond_on_same_app(self) -> None:
        """Both /workflows/{id}/ and /ag-ui/{id}/ return 200 on the same app.

        Verifies AC #1 + AC #2: both endpoint types coexist without conflict.
        """
        workflow = _make_workflow()

        # Build per-workflow handler
        with patch("beddel_serve_fastapi.handler.WorkflowExecutor") as mock_cls:
            mock_executor = MagicMock()
            mock_executor.execute_stream = MagicMock(
                return_value=_mock_event_stream(*_standard_events()),
            )
            mock_executor.execute = AsyncMock(
                return_value={
                    "step_results": {"generate": {"content": "hello"}},
                    "metadata": {},
                }
            )
            mock_cls.return_value = mock_executor
            per_wf_router = create_beddel_handler(workflow)

        # Build AG-UI endpoint
        with patch("beddel_ag_ui.endpoint.WorkflowExecutor") as mock_cls:
            mock_executor = MagicMock()
            mock_executor.execute_stream = MagicMock(
                return_value=_mock_event_stream(*_standard_events()),
            )
            mock_cls.return_value = mock_executor
            agui_router = create_agui_endpoint(workflow)

        app = FastAPI()
        app.include_router(per_wf_router, prefix=f"/workflows/{workflow.id}")
        app.include_router(agui_router, prefix=f"/ag-ui/{workflow.id}")

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            # Hit per-workflow endpoint
            wf_resp = await client.post(
                f"/workflows/{_WORKFLOW_ID}/",
                json={},
            )
            assert wf_resp.status_code == 200

            # Hit AG-UI endpoint
            agui_resp = await client.post(
                f"/ag-ui/{_WORKFLOW_ID}/",
                json={},
            )
            assert agui_resp.status_code == 200

        # Verify different SSE event naming conventions
        wf_events = _parse_sse_events(wf_resp.text)
        wf_types = [e["event"] for e in wf_events if "event" in e]
        assert "workflow_start" in wf_types  # Beddel native: snake_case

        agui_events = _parse_sse_events(agui_resp.text)
        agui_types = [e["event"] for e in agui_events if "event" in e]
        assert "RUN_STARTED" in agui_types  # AG-UI protocol: UPPER_CASE


# ---------------------------------------------------------------------------
# CORS headers on AG-UI endpoint (subtask 4.4) — AC #3
# ---------------------------------------------------------------------------


class TestCORSHeaders:
    """Verify CORS middleware covers AG-UI endpoints."""

    @pytest.mark.asyncio
    async def test_cors_headers_present_on_agui_response(self) -> None:
        """Response to AG-UI endpoint includes access-control-allow-origin.

        Verifies AC #3: CORS middleware configured on the same FastAPI app
        covers AG-UI endpoints.
        """
        app = _build_combined_app()

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            response = await client.post(
                f"/ag-ui/{_WORKFLOW_ID}/",
                json={"topic": "cors-test"},
                headers={"Origin": "http://localhost:3000"},
            )

        assert response.status_code == 200
        assert "access-control-allow-origin" in response.headers
        assert response.headers["access-control-allow-origin"] == "http://localhost:3000"

    @pytest.mark.asyncio
    async def test_cors_preflight_on_agui_endpoint(self) -> None:
        """OPTIONS preflight to AG-UI endpoint returns CORS headers.

        Verifies AC #3: CORS preflight (OPTIONS) works for AG-UI endpoints.
        """
        app = _build_combined_app()

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            response = await client.options(
                f"/ag-ui/{_WORKFLOW_ID}/",
                headers={
                    "Origin": "http://localhost:3000",
                    "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": "content-type",
                },
            )

        assert response.status_code == 200
        assert "access-control-allow-origin" in response.headers
        assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
        assert "access-control-allow-methods" in response.headers

    @pytest.mark.asyncio
    async def test_cors_headers_present_on_per_workflow_response(self) -> None:
        """CORS headers also present on per-workflow endpoint (same app).

        Verifies AC #3: CORS middleware covers both endpoint types equally.
        """
        app = _build_combined_app()

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            response = await client.post(
                f"/workflows/{_WORKFLOW_ID}/",
                json={},
                headers={"Origin": "http://localhost:3000"},
            )

        assert response.status_code == 200
        assert "access-control-allow-origin" in response.headers
        assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
