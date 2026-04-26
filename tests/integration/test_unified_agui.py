"""Integration tests for unified AG-UI endpoint (Story BC7.4, Task 4).

Tests the ``create_unified_agui_endpoint`` factory that creates a single
``POST /`` endpoint routing by ``workflow_id`` across multiple loaded
workflows.

Uses ``httpx.AsyncClient`` with ``ASGITransport`` — no real server needed.

AC #1: ``POST /ag-ui`` extracts ``workflow_id`` from ``state.workflow_id``
       or ``forwarded_props.workflow_id``.
AC #2: Single workflow loaded → used as default (no ``workflow_id`` needed).
AC #3: Unknown ``workflow_id`` → 422 with available IDs.
AC #4: Executes via ``WorkflowExecutor.execute_stream()`` →
       ``BeddelAGUIAdapter`` → SSE.
AC #7: Per-workflow endpoints (``POST /ag-ui/{id}/``) remain functional
       alongside the unified endpoint.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from unittest.mock import MagicMock

import httpx
import pytest
from beddel_ag_ui.endpoint import create_agui_endpoint
from beddel_ag_ui.unified import create_unified_agui_endpoint
from fastapi import FastAPI

from beddel.domain.models import BeddelEvent, EventType, Step, Workflow

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_WF_ID_1 = "wf-alpha"
_WF_ID_2 = "wf-beta"


def _make_workflow(wf_id: str, name: str = "Test Workflow") -> Workflow:
    """Create a minimal single-step workflow."""
    return Workflow(
        id=wf_id,
        name=name,
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


def _build_mock_executor() -> MagicMock:
    """Build a mock WorkflowExecutor whose ``execute_stream`` returns fresh generators."""
    mock = MagicMock()
    mock.execute_stream = MagicMock(
        side_effect=lambda *a, **kw: _mock_event_stream(*_standard_events()),
    )
    return mock


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


def _build_unified_app(
    executors: dict[str, tuple[Workflow, MagicMock]],
) -> FastAPI:
    """Build a FastAPI app with the unified AG-UI endpoint mounted at ``/ag-ui``."""
    app = FastAPI(title="Beddel Test")
    router = create_unified_agui_endpoint(executors)  # type: ignore[arg-type]
    app.include_router(router, prefix="/ag-ui")
    return app


# ---------------------------------------------------------------------------
# Subtask 4.1 — Unified endpoint routing tests
# ---------------------------------------------------------------------------


class TestUnifiedRouteByStateWorkflowId:
    """POST /ag-ui/ with ``state.workflow_id`` routes to the correct workflow."""

    @pytest.mark.asyncio
    async def test_routes_to_workflow_via_state_workflow_id(self) -> None:
        """AC #1: workflow_id extracted from state.workflow_id."""
        wf1 = _make_workflow(_WF_ID_1, "Alpha")
        wf2 = _make_workflow(_WF_ID_2, "Beta")
        exec1 = _build_mock_executor()
        exec2 = _build_mock_executor()

        app = _build_unified_app({_WF_ID_1: (wf1, exec1), _WF_ID_2: (wf2, exec2)})

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/ag-ui/",
                json={"state": {"workflow_id": _WF_ID_1, "topic": "test"}},
            )

        assert resp.status_code == 200
        exec1.execute_stream.assert_called_once()
        exec2.execute_stream.assert_not_called()

    @pytest.mark.asyncio
    async def test_routes_to_second_workflow_via_state(self) -> None:
        """AC #1: routing selects the second workflow when requested."""
        wf1 = _make_workflow(_WF_ID_1)
        wf2 = _make_workflow(_WF_ID_2)
        exec1 = _build_mock_executor()
        exec2 = _build_mock_executor()

        app = _build_unified_app({_WF_ID_1: (wf1, exec1), _WF_ID_2: (wf2, exec2)})

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/ag-ui/",
                json={"state": {"workflow_id": _WF_ID_2}},
            )

        assert resp.status_code == 200
        exec2.execute_stream.assert_called_once()
        exec1.execute_stream.assert_not_called()


class TestUnifiedRouteByForwardedProps:
    """POST /ag-ui/ with ``forwarded_props.workflow_id`` routes correctly."""

    @pytest.mark.asyncio
    async def test_routes_via_forwarded_props_workflow_id(self) -> None:
        """AC #1: workflow_id extracted from forwarded_props.workflow_id."""
        wf1 = _make_workflow(_WF_ID_1)
        wf2 = _make_workflow(_WF_ID_2)
        exec1 = _build_mock_executor()
        exec2 = _build_mock_executor()

        app = _build_unified_app({_WF_ID_1: (wf1, exec1), _WF_ID_2: (wf2, exec2)})

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/ag-ui/",
                json={"forwarded_props": {"workflow_id": _WF_ID_2}},
            )

        assert resp.status_code == 200
        exec2.execute_stream.assert_called_once()
        exec1.execute_stream.assert_not_called()

    @pytest.mark.asyncio
    async def test_state_takes_precedence_over_forwarded_props(self) -> None:
        """AC #1: state.workflow_id is checked before forwarded_props."""
        wf1 = _make_workflow(_WF_ID_1)
        wf2 = _make_workflow(_WF_ID_2)
        exec1 = _build_mock_executor()
        exec2 = _build_mock_executor()

        app = _build_unified_app({_WF_ID_1: (wf1, exec1), _WF_ID_2: (wf2, exec2)})

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/ag-ui/",
                json={
                    "state": {"workflow_id": _WF_ID_1},
                    "forwarded_props": {"workflow_id": _WF_ID_2},
                },
            )

        assert resp.status_code == 200
        exec1.execute_stream.assert_called_once()
        exec2.execute_stream.assert_not_called()


class TestUnifiedSingleWorkflowDefault:
    """POST /ag-ui/ with a single workflow uses it as default."""

    @pytest.mark.asyncio
    async def test_single_workflow_used_as_default(self) -> None:
        """AC #2: no workflow_id needed when only one workflow is loaded."""
        wf = _make_workflow(_WF_ID_1)
        executor = _build_mock_executor()

        app = _build_unified_app({_WF_ID_1: (wf, executor)})

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/ag-ui/", json={"state": {"topic": "test"}})

        assert resp.status_code == 200
        executor.execute_stream.assert_called_once()

    @pytest.mark.asyncio
    async def test_single_workflow_with_empty_body(self) -> None:
        """AC #2: empty body still routes to the single workflow."""
        wf = _make_workflow(_WF_ID_1)
        executor = _build_mock_executor()

        app = _build_unified_app({_WF_ID_1: (wf, executor)})

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/ag-ui/", json={})

        assert resp.status_code == 200
        executor.execute_stream.assert_called_once()


class TestUnifiedUnknownWorkflowId:
    """POST /ag-ui/ with unknown workflow_id returns 422."""

    @pytest.mark.asyncio
    async def test_unknown_workflow_id_returns_422(self) -> None:
        """AC #3: 422 with available workflow IDs when ID not found."""
        wf = _make_workflow(_WF_ID_1)
        executor = _build_mock_executor()

        app = _build_unified_app({_WF_ID_1: (wf, executor)})

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/ag-ui/",
                json={"state": {"workflow_id": "nonexistent"}},
            )

        assert resp.status_code == 422
        body = resp.json()
        assert body["code"] == "BEDDEL-AGUI-002"
        assert _WF_ID_1 in body["message"]

    @pytest.mark.asyncio
    async def test_422_lists_all_available_ids(self) -> None:
        """AC #3: 422 response lists all available workflow IDs."""
        wf1 = _make_workflow(_WF_ID_1)
        wf2 = _make_workflow(_WF_ID_2)
        exec1 = _build_mock_executor()
        exec2 = _build_mock_executor()

        app = _build_unified_app({_WF_ID_1: (wf1, exec1), _WF_ID_2: (wf2, exec2)})

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/ag-ui/",
                json={"state": {"workflow_id": "missing"}},
            )

        assert resp.status_code == 422
        body = resp.json()
        assert _WF_ID_1 in body["message"]
        assert _WF_ID_2 in body["message"]


class TestUnifiedNoWorkflowIdMultiple:
    """POST /ag-ui/ with no workflow_id and multiple workflows returns 422."""

    @pytest.mark.asyncio
    async def test_no_workflow_id_multiple_workflows_returns_422(self) -> None:
        """AC #3: ambiguous request with multiple workflows → 422."""
        wf1 = _make_workflow(_WF_ID_1)
        wf2 = _make_workflow(_WF_ID_2)
        exec1 = _build_mock_executor()
        exec2 = _build_mock_executor()

        app = _build_unified_app({_WF_ID_1: (wf1, exec1), _WF_ID_2: (wf2, exec2)})

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/ag-ui/", json={"state": {"topic": "test"}})

        assert resp.status_code == 422
        body = resp.json()
        assert body["code"] == "BEDDEL-AGUI-002"
        assert _WF_ID_1 in body["message"]
        assert _WF_ID_2 in body["message"]


class TestUnifiedSSEStream:
    """POST /ag-ui/ returns SSE stream with AG-UI events."""

    @pytest.mark.asyncio
    async def test_returns_sse_with_run_started_and_finished(self) -> None:
        """AC #4: SSE stream contains RUN_STARTED and RUN_FINISHED events."""
        wf = _make_workflow(_WF_ID_1)
        executor = _build_mock_executor()

        app = _build_unified_app({_WF_ID_1: (wf, executor)})

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/ag-ui/",
                json={"state": {"workflow_id": _WF_ID_1}},
            )

        assert resp.status_code == 200
        content_type = resp.headers.get("content-type", "")
        assert "text/event-stream" in content_type

        events = _parse_sse_events(resp.text)
        event_types = [e["event"] for e in events if "event" in e]
        assert "RUN_STARTED" in event_types
        assert "RUN_FINISHED" in event_types

    @pytest.mark.asyncio
    async def test_sse_stream_contains_step_and_text_events(self) -> None:
        """AC #4: SSE stream includes STEP_STARTED, TEXT_MESSAGE_*, STEP_FINISHED."""
        wf = _make_workflow(_WF_ID_1)
        executor = _build_mock_executor()

        app = _build_unified_app({_WF_ID_1: (wf, executor)})

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/ag-ui/",
                json={"state": {"workflow_id": _WF_ID_1}},
            )

        events = _parse_sse_events(resp.text)
        event_types = [e["event"] for e in events if "event" in e]
        assert "STEP_STARTED" in event_types
        assert "STEP_FINISHED" in event_types
        assert "TEXT_MESSAGE_START" in event_types
        assert "TEXT_MESSAGE_CONTENT" in event_types
        assert "TEXT_MESSAGE_END" in event_types


class TestUnifiedInvalidJSON:
    """POST /ag-ui/ with invalid JSON returns 400."""

    @pytest.mark.asyncio
    async def test_invalid_json_returns_400(self) -> None:
        """Invalid JSON body → 400 with BEDDEL-AGUI-001 error code."""
        wf = _make_workflow(_WF_ID_1)
        executor = _build_mock_executor()

        app = _build_unified_app({_WF_ID_1: (wf, executor)})

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/ag-ui/",
                content=b"not-valid-json{{{",
                headers={"content-type": "application/json"},
            )

        assert resp.status_code == 400
        body = resp.json()
        assert body["code"] == "BEDDEL-AGUI-001"


# ---------------------------------------------------------------------------
# Subtask 4.2 — Per-workflow endpoints coexist with unified endpoint
# ---------------------------------------------------------------------------


class TestPerWorkflowCoexistence:
    """Per-workflow endpoints (POST /ag-ui/{id}/) work alongside unified."""

    @pytest.mark.asyncio
    async def test_per_workflow_endpoint_works_with_unified(self) -> None:
        """AC #7: per-workflow endpoint returns SSE when unified is also mounted."""
        wf = _make_workflow(_WF_ID_1)
        unified_executor = _build_mock_executor()

        app = FastAPI(title="Beddel Test")

        # Mount unified endpoint
        unified_router = create_unified_agui_endpoint(
            {_WF_ID_1: (wf, unified_executor)},  # type: ignore[dict-item]
        )
        app.include_router(unified_router, prefix="/ag-ui")

        # Mount per-workflow endpoint (uses its own internal executor)
        from unittest.mock import patch

        with patch("beddel_ag_ui.endpoint.WorkflowExecutor") as mock_cls:
            per_wf_executor = MagicMock()
            per_wf_executor.execute_stream = MagicMock(
                side_effect=lambda *a, **kw: _mock_event_stream(*_standard_events()),
            )
            mock_cls.return_value = per_wf_executor
            per_wf_router = create_agui_endpoint(wf)

        app.include_router(per_wf_router, prefix=f"/ag-ui/{_WF_ID_1}")

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            # Hit per-workflow endpoint
            per_wf_resp = await client.post(
                f"/ag-ui/{_WF_ID_1}/",
                json={"topic": "testing"},
            )

        assert per_wf_resp.status_code == 200
        content_type = per_wf_resp.headers.get("content-type", "")
        assert "text/event-stream" in content_type

        events = _parse_sse_events(per_wf_resp.text)
        event_types = [e["event"] for e in events if "event" in e]
        assert "RUN_STARTED" in event_types
        assert "RUN_FINISHED" in event_types

    @pytest.mark.asyncio
    async def test_both_unified_and_per_workflow_respond(self) -> None:
        """AC #7: both unified and per-workflow endpoints return 200 on same app."""
        wf = _make_workflow(_WF_ID_1)
        unified_executor = _build_mock_executor()

        app = FastAPI(title="Beddel Test")

        # Mount unified endpoint
        unified_router = create_unified_agui_endpoint(
            {_WF_ID_1: (wf, unified_executor)},  # type: ignore[dict-item]
        )
        app.include_router(unified_router, prefix="/ag-ui")

        # Mount per-workflow endpoint
        from unittest.mock import patch

        with patch("beddel_ag_ui.endpoint.WorkflowExecutor") as mock_cls:
            per_wf_executor = MagicMock()
            per_wf_executor.execute_stream = MagicMock(
                side_effect=lambda *a, **kw: _mock_event_stream(*_standard_events()),
            )
            mock_cls.return_value = per_wf_executor
            per_wf_router = create_agui_endpoint(wf)

        app.include_router(per_wf_router, prefix=f"/ag-ui/{_WF_ID_1}")

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            # Unified endpoint
            unified_resp = await client.post(
                "/ag-ui/",
                json={"state": {"workflow_id": _WF_ID_1}},
            )
            assert unified_resp.status_code == 200

            # Per-workflow endpoint
            per_wf_resp = await client.post(
                f"/ag-ui/{_WF_ID_1}/",
                json={"topic": "testing"},
            )
            assert per_wf_resp.status_code == 200

        # Both return SSE streams with AG-UI events
        unified_events = _parse_sse_events(unified_resp.text)
        unified_types = [e["event"] for e in unified_events if "event" in e]
        assert "RUN_STARTED" in unified_types

        per_wf_events = _parse_sse_events(per_wf_resp.text)
        per_wf_types = [e["event"] for e in per_wf_events if "event" in e]
        assert "RUN_STARTED" in per_wf_types
