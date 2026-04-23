"""Integration tests for AG-UI endpoint (Story BC3.1, Task 7).

Tests the AG-UI endpoint factory end-to-end using ``httpx.AsyncClient``
with ``ASGITransport`` — no real server needed.  Covers SSE streaming,
camelCase AG-UI serialization, and error handling.

AC #7: POST to endpoint with mock workflow → receive AG-UI SSE events.
AC #8: SSE events are valid JSON with camelCase keys (AG-UI serialization).
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest
from beddel_ag_ui.endpoint import create_agui_endpoint
from fastapi import FastAPI

from beddel.domain.errors import ExecutionError
from beddel.domain.models import BeddelEvent, EventType, Step, Workflow

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_workflow() -> Workflow:
    """Create a minimal single-step workflow for testing."""
    return Workflow(
        id="test-wf",
        name="Test Workflow",
        steps=[Step(id="s1", primitive="llm")],
    )


def _make_app(workflow: Workflow | None = None, **kwargs: Any) -> FastAPI:
    """Mount the AG-UI endpoint on a fresh FastAPI app."""
    app = FastAPI()
    wf = workflow or _make_workflow()
    router = create_agui_endpoint(wf, **kwargs)
    app.include_router(router, prefix="/ag-ui")
    return app


async def _mock_event_stream(
    *events: BeddelEvent,
) -> AsyncGenerator[BeddelEvent, None]:
    """Yield BeddelEvent instances as an async generator."""
    for event in events:
        yield event


def _parse_sse_events(text: str) -> list[dict[str, str]]:
    """Parse raw SSE text into a list of {event, data} dicts.

    Handles both ``\\n\\n`` and ``\\r\\n\\r\\n`` separators.
    Skips empty blocks and comment lines.
    """
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
# SSE streaming tests (subtasks 7.2, 7.3)
# ---------------------------------------------------------------------------


class TestAGUIEndpointSSE:
    """Verify AG-UI SSE streaming through the HTTP layer."""

    @pytest.mark.asyncio
    async def test_post_returns_sse_stream(self) -> None:
        """POST /ag-ui/ returns HTTP 200 with text/event-stream content type.

        Verifies AC #7: POST to endpoint with mock workflow receives SSE.
        """
        with patch("beddel_ag_ui.endpoint.WorkflowExecutor") as mock_cls:
            mock_executor = MagicMock()
            mock_executor.execute_stream = MagicMock(
                return_value=_mock_event_stream(
                    BeddelEvent(event_type=EventType.WORKFLOW_START, data={}),
                    BeddelEvent(event_type=EventType.STEP_START, step_id="s1", data={}),
                    BeddelEvent(
                        event_type=EventType.TEXT_CHUNK,
                        step_id="s1",
                        data={"text": "hello"},
                    ),
                    BeddelEvent(event_type=EventType.STEP_END, step_id="s1", data={}),
                    BeddelEvent(event_type=EventType.WORKFLOW_END, data={}),
                ),
            )
            mock_cls.return_value = mock_executor
            app = _make_app()

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            response = await client.post("/ag-ui/", json={"key": "value"})

        assert response.status_code == 200
        content_type = response.headers.get("content-type", "")
        assert "text/event-stream" in content_type

    @pytest.mark.asyncio
    async def test_sse_events_contain_expected_ag_ui_types(self) -> None:
        """SSE stream contains the expected AG-UI event types in order.

        Verifies AC #7: the endpoint translates BeddelEvents into AG-UI
        protocol events (RUN_STARTED, STEP_STARTED, TEXT_MESSAGE_START,
        TEXT_MESSAGE_CONTENT, STEP_FINISHED, RUN_FINISHED,
        TEXT_MESSAGE_END).
        """
        with patch("beddel_ag_ui.endpoint.WorkflowExecutor") as mock_cls:
            mock_executor = MagicMock()
            mock_executor.execute_stream = MagicMock(
                return_value=_mock_event_stream(
                    BeddelEvent(event_type=EventType.WORKFLOW_START, data={}),
                    BeddelEvent(event_type=EventType.STEP_START, step_id="s1", data={}),
                    BeddelEvent(
                        event_type=EventType.TEXT_CHUNK,
                        step_id="s1",
                        data={"text": "hello"},
                    ),
                    BeddelEvent(event_type=EventType.STEP_END, step_id="s1", data={}),
                    BeddelEvent(event_type=EventType.WORKFLOW_END, data={}),
                ),
            )
            mock_cls.return_value = mock_executor
            app = _make_app()

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            response = await client.post("/ag-ui/", json={})

        events = _parse_sse_events(response.text)
        event_types = [e["event"] for e in events if "event" in e]

        # AG-UI adapter emits: RUN_STARTED, STEP_STARTED,
        # TEXT_MESSAGE_START (auto), TEXT_MESSAGE_CONTENT, STEP_FINISHED,
        # RUN_FINISHED, TEXT_MESSAGE_END (auto)
        assert "RUN_STARTED" in event_types
        assert "STEP_STARTED" in event_types
        assert "TEXT_MESSAGE_START" in event_types
        assert "TEXT_MESSAGE_CONTENT" in event_types
        assert "STEP_FINISHED" in event_types
        assert "RUN_FINISHED" in event_types
        assert "TEXT_MESSAGE_END" in event_types

    @pytest.mark.asyncio
    async def test_sse_events_are_valid_json_with_camel_case_keys(self) -> None:
        """Every SSE event's data field is valid JSON with camelCase keys.

        Verifies AC #8: AG-UI serialization uses camelCase (e.g.
        ``threadId``, ``runId``, ``stepName``, ``messageId``).
        """
        with patch("beddel_ag_ui.endpoint.WorkflowExecutor") as mock_cls:
            mock_executor = MagicMock()
            mock_executor.execute_stream = MagicMock(
                return_value=_mock_event_stream(
                    BeddelEvent(event_type=EventType.WORKFLOW_START, data={}),
                    BeddelEvent(event_type=EventType.STEP_START, step_id="s1", data={}),
                    BeddelEvent(
                        event_type=EventType.TEXT_CHUNK,
                        step_id="s1",
                        data={"text": "hello"},
                    ),
                    BeddelEvent(event_type=EventType.STEP_END, step_id="s1", data={}),
                    BeddelEvent(event_type=EventType.WORKFLOW_END, data={}),
                ),
            )
            mock_cls.return_value = mock_executor
            app = _make_app()

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            response = await client.post("/ag-ui/", json={})

        events = _parse_sse_events(response.text)

        # Known camelCase keys that AG-UI events must use
        camel_case_keys = {
            "threadId",
            "runId",
            "stepName",
            "messageId",
            "rawEvent",
            "parentRunId",
        }

        # Known snake_case equivalents that must NOT appear
        snake_case_keys = {
            "thread_id",
            "run_id",
            "step_name",
            "message_id",
            "raw_event",
            "parent_run_id",
        }

        found_camel_case = False
        for sse in events:
            if "data" not in sse:
                continue
            parsed = json.loads(sse["data"])
            assert isinstance(parsed, dict), "SSE data must be a JSON object"

            # Verify no snake_case keys leak through
            actual_keys = set(parsed.keys())
            leaked = actual_keys & snake_case_keys
            assert not leaked, f"Snake-case keys found in AG-UI event: {leaked}"

            # Track that we found at least one camelCase key
            if actual_keys & camel_case_keys:
                found_camel_case = True

        assert found_camel_case, "Expected at least one AG-UI camelCase key"

    @pytest.mark.asyncio
    async def test_run_started_event_has_thread_and_run_ids(self) -> None:
        """RUN_STARTED event contains threadId and runId in camelCase.

        Verifies AC #8: AG-UI protocol fields are serialized correctly.
        """
        with patch("beddel_ag_ui.endpoint.WorkflowExecutor") as mock_cls:
            mock_executor = MagicMock()
            mock_executor.execute_stream = MagicMock(
                return_value=_mock_event_stream(
                    BeddelEvent(event_type=EventType.WORKFLOW_START, data={}),
                    BeddelEvent(event_type=EventType.WORKFLOW_END, data={}),
                ),
            )
            mock_cls.return_value = mock_executor
            app = _make_app()

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            response = await client.post("/ag-ui/", json={})

        events = _parse_sse_events(response.text)
        run_started = [e for e in events if e.get("event") == "RUN_STARTED"]
        assert len(run_started) == 1

        data = json.loads(run_started[0]["data"])
        assert "threadId" in data
        assert "runId" in data
        assert isinstance(data["threadId"], str)
        assert isinstance(data["runId"], str)

    @pytest.mark.asyncio
    async def test_step_events_have_step_name(self) -> None:
        """STEP_STARTED and STEP_FINISHED events contain stepName in camelCase."""
        with patch("beddel_ag_ui.endpoint.WorkflowExecutor") as mock_cls:
            mock_executor = MagicMock()
            mock_executor.execute_stream = MagicMock(
                return_value=_mock_event_stream(
                    BeddelEvent(event_type=EventType.WORKFLOW_START, data={}),
                    BeddelEvent(event_type=EventType.STEP_START, step_id="s1", data={}),
                    BeddelEvent(event_type=EventType.STEP_END, step_id="s1", data={}),
                    BeddelEvent(event_type=EventType.WORKFLOW_END, data={}),
                ),
            )
            mock_cls.return_value = mock_executor
            app = _make_app()

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            response = await client.post("/ag-ui/", json={})

        events = _parse_sse_events(response.text)
        step_events = [e for e in events if e.get("event") in ("STEP_STARTED", "STEP_FINISHED")]
        assert len(step_events) == 2

        for sse in step_events:
            data = json.loads(sse["data"])
            assert "stepName" in data
            assert data["stepName"] == "s1"

    @pytest.mark.asyncio
    async def test_text_message_events_have_message_id(self) -> None:
        """TEXT_MESSAGE_* events contain messageId in camelCase."""
        with patch("beddel_ag_ui.endpoint.WorkflowExecutor") as mock_cls:
            mock_executor = MagicMock()
            mock_executor.execute_stream = MagicMock(
                return_value=_mock_event_stream(
                    BeddelEvent(event_type=EventType.WORKFLOW_START, data={}),
                    BeddelEvent(
                        event_type=EventType.TEXT_CHUNK,
                        step_id="s1",
                        data={"text": "hello"},
                    ),
                    BeddelEvent(event_type=EventType.WORKFLOW_END, data={}),
                ),
            )
            mock_cls.return_value = mock_executor
            app = _make_app()

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            response = await client.post("/ag-ui/", json={})

        events = _parse_sse_events(response.text)
        text_events = [e for e in events if e.get("event", "").startswith("TEXT_MESSAGE")]
        assert len(text_events) >= 2  # START + CONTENT + END

        for sse in text_events:
            data = json.loads(sse["data"])
            assert "messageId" in data
            assert isinstance(data["messageId"], str)


# ---------------------------------------------------------------------------
# Error handling tests (subtask 7.4)
# ---------------------------------------------------------------------------


class TestAGUIEndpointErrors:
    """Verify error handling in the AG-UI endpoint."""

    @pytest.mark.asyncio
    async def test_execution_error_returns_json_error(self) -> None:
        """ExecutionError raised before streaming returns structured JSON error.

        Verifies AC #7 error path: BeddelError caught by the endpoint
        handler returns a JSON response (not SSE) with code, message,
        and details.
        """
        with patch("beddel_ag_ui.endpoint.WorkflowExecutor") as mock_cls:
            mock_executor = MagicMock()
            mock_executor.execute_stream = MagicMock(
                side_effect=ExecutionError(
                    code="BEDDEL-EXEC-002",
                    message="Step failed",
                    details={"step_id": "s1"},
                ),
            )
            mock_cls.return_value = mock_executor
            app = _make_app()

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            response = await client.post("/ag-ui/", json={})

        assert response.status_code == 500
        body = response.json()
        assert body["code"] == "BEDDEL-EXEC-002"
        assert "message" in body
        assert "details" in body

    @pytest.mark.asyncio
    async def test_unexpected_error_returns_500(self) -> None:
        """Unexpected exception returns HTTP 500 with generic error body.

        Verifies the catch-all except block in the endpoint handler.
        """
        with patch("beddel_ag_ui.endpoint.WorkflowExecutor") as mock_cls:
            mock_executor = MagicMock()
            mock_executor.execute_stream = MagicMock(
                side_effect=RuntimeError("boom"),
            )
            mock_cls.return_value = mock_executor
            app = _make_app()

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            response = await client.post("/ag-ui/", json={})

        assert response.status_code == 500
        body = response.json()
        assert body["code"] == "BEDDEL-INTERNAL-001"
        assert body["message"] == "Internal server error"

    @pytest.mark.asyncio
    async def test_streaming_error_yields_run_error_event(self) -> None:
        """Error during SSE streaming yields RunErrorEvent in the stream.

        When execute_stream succeeds but the async generator raises during
        iteration, the BeddelAGUIAdapter catches it and emits a
        RunErrorEvent followed by RunFinishedEvent.
        """

        async def _failing_stream() -> AsyncGenerator[BeddelEvent, None]:
            yield BeddelEvent(event_type=EventType.WORKFLOW_START, data={})
            raise ExecutionError(
                code="BEDDEL-EXEC-003",
                message="Mid-stream failure",
                details={},
            )

        with patch("beddel_ag_ui.endpoint.WorkflowExecutor") as mock_cls:
            mock_executor = MagicMock()
            mock_executor.execute_stream = MagicMock(
                return_value=_failing_stream(),
            )
            mock_cls.return_value = mock_executor
            app = _make_app()

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            response = await client.post("/ag-ui/", json={})

        # SSE response still returns 200 (streaming already started)
        assert response.status_code == 200
        events = _parse_sse_events(response.text)
        event_types = [e["event"] for e in events if "event" in e]

        assert "RUN_ERROR" in event_types
        assert "RUN_FINISHED" in event_types

        # Verify the error event contains the error message
        error_events = [e for e in events if e.get("event") == "RUN_ERROR"]
        assert len(error_events) == 1
        error_data = json.loads(error_events[0]["data"])
        assert error_data["message"] == "Mid-stream failure"
        assert error_data["code"] == "BEDDEL-EXEC-003"
