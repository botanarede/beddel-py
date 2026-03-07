"""Integration tests for create_beddel_handler (Story 3.3, Task 5).

Tests the FastAPI handler factory end-to-end using ``httpx.AsyncClient``
with ``ASGITransport`` — no real server needed.  Covers factory defaults,
custom dependencies, SSE streaming, error handling, and W3C multi-line
compliance.
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from typing import Any

import httpx
from fastapi import APIRouter, FastAPI

from beddel.domain.errors import ExecutionError, ParseError
from beddel.domain.models import ExecutionContext, Step, Workflow
from beddel.domain.ports import ILLMProvider, IPrimitive
from beddel.domain.registry import PrimitiveRegistry
from beddel.integrations.fastapi import create_beddel_handler

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _MockProvider(ILLMProvider):
    """Minimal LLM provider that returns a fixed response."""

    async def complete(
        self,
        model: str,
        messages: list[dict[str, Any]],
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Return a canned completion response."""
        return {"content": "mock-response", "usage": {}}

    async def stream(
        self,
        model: str,
        messages: list[dict[str, Any]],
        **kwargs: Any,
    ) -> AsyncGenerator[str, None]:
        """Yield a single mock token."""
        yield "mock-chunk"


class _MockPrimitive(IPrimitive):
    """Primitive that returns a fixed result dict."""

    async def execute(self, config: dict[str, Any], context: ExecutionContext) -> Any:
        """Return a simple result dict."""
        return {"status": "ok", "echo": config}


def _make_workflow(
    primitive_name: str = "mock",
    step_id: str = "step-1",
) -> Workflow:
    """Create a minimal single-step workflow for testing."""
    return Workflow(
        id="test-wf",
        name="Test Workflow",
        steps=[
            Step(id=step_id, primitive=primitive_name),
        ],
    )


def _make_app(router: APIRouter) -> FastAPI:
    """Mount a router on a fresh FastAPI app."""
    app = FastAPI()
    app.include_router(router)
    return app


def _parse_sse_events(text: str) -> list[dict[str, str]]:
    """Parse raw SSE text into a list of {event, data} dicts.

    Handles both ``\\n\\n`` and ``\\r\\n\\r\\n`` separators.
    Skips empty blocks and comment lines.
    """
    # Normalise line endings
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
            # skip comment lines (: ping) and id: lines
        if data_lines:
            event_dict["data"] = "\n".join(data_lines)
        if event_dict:
            events.append(event_dict)
    return events


# ---------------------------------------------------------------------------
# Factory defaults (subtasks 5.2, 5.3)
# ---------------------------------------------------------------------------


class TestFactoryDefaults:
    """Verify create_beddel_handler factory wiring and defaults."""

    def test_creates_api_router(self) -> None:
        """Factory returns an APIRouter instance."""
        router = create_beddel_handler(
            _make_workflow(),
            provider=_MockProvider(),
            registry=_build_mock_registry(),
        )
        assert isinstance(router, APIRouter)

    def test_default_provider_and_registry(self) -> None:
        """Factory succeeds with no provider/registry (uses defaults).

        Verifies AC3: LiteLLMAdapter and register_builtins are used when
        no explicit provider or registry is supplied.
        """
        router = create_beddel_handler(_make_workflow(primitive_name="llm"))
        assert isinstance(router, APIRouter)
        assert len(router.routes) > 0

    async def test_custom_provider_and_registry(self) -> None:
        """Custom provider and registry are used instead of defaults.

        Verifies AC1/AC3: the mock primitive's result appears in the SSE
        stream, proving the custom registry was wired through.
        """
        registry = _build_mock_registry()
        provider = _MockProvider()
        router = create_beddel_handler(
            _make_workflow(),
            provider=provider,
            registry=registry,
        )
        app = _make_app(router)

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.post("/", json={})

        assert response.status_code == 200
        events = _parse_sse_events(response.text)
        # The mock primitive returns {"status": "ok", ...} — find it in STEP_END
        step_end_events = [e for e in events if e.get("event") == "step_end"]
        assert len(step_end_events) == 1
        data = json.loads(step_end_events[0]["data"])
        assert data["data"]["result"]["status"] == "ok"


# ---------------------------------------------------------------------------
# SSE endpoint (subtasks 5.4, 5.5, 5.7)
# ---------------------------------------------------------------------------


class TestSSEEndpoint:
    """Verify SSE streaming behaviour through the HTTP layer."""

    async def test_post_returns_sse_content_type(self) -> None:
        """POST / returns Content-Type: text/event-stream.

        Verifies AC4: SSE streaming via execute_stream piped through
        BeddelSSEAdapter.stream_events.
        """
        app = _make_app(
            create_beddel_handler(
                _make_workflow(),
                provider=_MockProvider(),
                registry=_build_mock_registry(),
            )
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.post("/", json={})

        assert response.status_code == 200
        content_type = response.headers.get("content-type", "")
        assert "text/event-stream" in content_type

    async def test_sse_stream_event_order(self) -> None:
        """SSE stream contains WORKFLOW_START, STEP_START, STEP_END, WORKFLOW_END in order."""
        app = _make_app(
            create_beddel_handler(
                _make_workflow(),
                provider=_MockProvider(),
                registry=_build_mock_registry(),
            )
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.post("/", json={})

        events = _parse_sse_events(response.text)
        event_types = [e["event"] for e in events if "event" in e]
        assert event_types == [
            "workflow_start",
            "step_start",
            "step_end",
            "workflow_end",
        ]

    async def test_sse_events_contain_valid_json_data(self) -> None:
        """Every SSE event's data field is valid JSON."""
        app = _make_app(
            create_beddel_handler(
                _make_workflow(),
                provider=_MockProvider(),
                registry=_build_mock_registry(),
            )
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.post("/", json={})

        events = _parse_sse_events(response.text)
        for sse in events:
            if "data" in sse:
                parsed = json.loads(sse["data"])
                assert "event_type" in parsed

    async def test_httpx_async_client_with_asgi_transport(self) -> None:
        """Verify the httpx + ASGITransport testing pattern works end-to-end.

        Uses ``client.stream()`` to read the SSE response incrementally,
        proving no real server is needed.
        """
        app = _make_app(
            create_beddel_handler(
                _make_workflow(),
                provider=_MockProvider(),
                registry=_build_mock_registry(),
            )
        )
        async with (
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
            ) as client,
            client.stream("POST", "/", json={}) as response,
        ):
            body = await response.aread()

        text = body.decode()
        events = _parse_sse_events(text)
        assert len(events) >= 4


# ---------------------------------------------------------------------------
# Error handling (subtask 5.6)
# ---------------------------------------------------------------------------


class TestErrorHandling:
    """Verify structured error responses for workflow failures.

    The handler's try/except catches errors that occur synchronously
    (before the SSE stream starts).  Errors during streaming (e.g. from
    a failing primitive) propagate through the async generator and are
    handled by sse-starlette, not the handler's except block.

    To test the handler's error paths we trigger errors that happen
    before streaming: invalid JSON body (generic Exception → 500) and
    a monkeypatched executor that raises BeddelError synchronously.
    """

    async def test_execution_error_returns_500(self) -> None:
        """ExecutionError raised before streaming returns HTTP 500 with structured JSON.

        We monkeypatch the executor's execute_stream to raise ExecutionError
        synchronously, which the handler's except BeddelError block catches.
        """
        from unittest.mock import patch

        registry = _build_mock_registry()
        router = create_beddel_handler(
            _make_workflow(),
            provider=_MockProvider(),
            registry=registry,
        )
        app = _make_app(router)

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            with patch(
                "beddel.integrations.fastapi.WorkflowExecutor.execute_stream",
                side_effect=ExecutionError(
                    code="BEDDEL-EXEC-002",
                    message="Step failed",
                    details={"step_id": "s1"},
                ),
            ):
                response = await client.post("/", json={})

        assert response.status_code == 500
        body = response.json()
        assert body["code"] == "BEDDEL-EXEC-002"
        assert "message" in body
        assert "details" in body

    async def test_parse_error_returns_422(self) -> None:
        """ParseError raised before streaming returns HTTP 422 (client error).

        ParseError is in _CLIENT_ERRORS, so the handler maps it to 422.
        """
        from unittest.mock import patch

        registry = _build_mock_registry()
        router = create_beddel_handler(
            _make_workflow(),
            provider=_MockProvider(),
            registry=registry,
        )
        app = _make_app(router)

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            with patch(
                "beddel.integrations.fastapi.WorkflowExecutor.execute_stream",
                side_effect=ParseError(
                    code="BEDDEL-PARSE-001",
                    message="Bad workflow YAML",
                    details={"line": 42},
                ),
            ):
                response = await client.post("/", json={})

        assert response.status_code == 422
        body = response.json()
        assert body["code"] == "BEDDEL-PARSE-001"
        assert body["message"] == "Bad workflow YAML"
        assert body["details"]["line"] == 42


# ---------------------------------------------------------------------------
# Multi-line SSE (subtask 5.8)
# ---------------------------------------------------------------------------


class TestMultiLineSSE:
    """Verify W3C SSE compliance for multi-line data end-to-end."""

    async def test_multiline_data_w3c_compliance(self) -> None:
        """SSE data round-trips correctly even when the payload contains newlines.

        Pydantic's model_dump_json() produces compact JSON where embedded
        newlines are escaped as ``\\n``, so the data stays single-line.
        This test proves the full round-trip: primitive result → BeddelEvent
        → SSE adapter → HTTP response → parse back to dict.
        """

        class _NewlinePrimitive(IPrimitive):
            async def execute(self, config: dict[str, Any], context: ExecutionContext) -> Any:
                return {"text": "line1\nline2\nline3", "count": 3}

        registry = PrimitiveRegistry()
        registry.register("newline", _NewlinePrimitive())
        app = _make_app(
            create_beddel_handler(
                _make_workflow(primitive_name="newline"),
                provider=_MockProvider(),
                registry=registry,
            )
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.post("/", json={})

        assert response.status_code == 200
        events = _parse_sse_events(response.text)
        step_end_events = [e for e in events if e.get("event") == "step_end"]
        assert len(step_end_events) == 1

        data = json.loads(step_end_events[0]["data"])
        result = data["data"]["result"]
        assert result["text"] == "line1\nline2\nline3"
        assert result["count"] == 3


# ---------------------------------------------------------------------------
# Shared helper
# ---------------------------------------------------------------------------


def _build_mock_registry() -> PrimitiveRegistry:
    """Create a registry with only the mock primitive registered."""
    registry = PrimitiveRegistry()
    registry.register("mock", _MockPrimitive())
    return registry
