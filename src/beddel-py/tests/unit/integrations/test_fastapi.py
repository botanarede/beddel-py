"""Unit tests for the FastAPI integration — factory, blocking handler, and SSE streaming."""

from __future__ import annotations

import builtins
import importlib
import inspect
import json
import sys
import tempfile
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, patch

import pytest
import yaml
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from beddel.domain.models import (
    ConfigurationError,
    ErrorCode,
    ExecutionError,
    ExecutionResult,
    ParseError,
    ProviderError,
    StepDefinition,
    WorkflowDefinition,
    WorkflowMetadata,
)
from beddel.domain.registry import PrimitiveRegistry
from beddel.integrations.fastapi import create_beddel_handler

if TYPE_CHECKING:
    from collections.abc import AsyncIterator as AsyncIteratorABC

# ---------------------------------------------------------------------------
# Test-app helper
# ---------------------------------------------------------------------------


def _mount_handler(handler: Any) -> FastAPI:
    """Create a FastAPI app with the handler mounted at POST /run.

    Uses ``response_model=None`` to avoid FastAPI trying to infer a
    response model from the ``JSONResponse | EventSourceResponse`` union.
    """
    app = FastAPI()
    app.add_api_route("/run", handler, methods=["POST"], response_model=None)
    return app

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_workflow() -> WorkflowDefinition:
    """Build a minimal non-streaming WorkflowDefinition for testing."""
    return WorkflowDefinition(
        metadata=WorkflowMetadata(name="test-workflow"),
        workflow=[
            StepDefinition(id="step-1", type="llm", config={"model": "gpt-4o"}),
        ],
    )


def _make_result(**overrides: Any) -> ExecutionResult:
    """Build a controlled ExecutionResult for mocking."""
    defaults: dict[str, Any] = {
        "workflow_id": "test-123",
        "success": True,
        "output": "Hello from Beddel!",
    }
    defaults.update(overrides)
    return ExecutionResult(**defaults)


def _make_yaml_data() -> dict[str, Any]:
    """Build a minimal YAML-serializable workflow dict."""
    return {
        "metadata": {"name": "yaml-agent", "version": "1.0.0"},
        "workflow": [
            {"id": "step-1", "type": "llm", "config": {"model": "gpt-4o"}},
        ],
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def workflow_def() -> WorkflowDefinition:
    """Minimal non-streaming WorkflowDefinition."""
    return _make_workflow()


@pytest.fixture
def registry() -> PrimitiveRegistry:
    """Empty PrimitiveRegistry (executor is mocked, so no primitives needed)."""
    return PrimitiveRegistry()


@pytest.fixture
def mock_result() -> ExecutionResult:
    """Controlled ExecutionResult for mocking."""
    return _make_result()


# ---------------------------------------------------------------------------
# 4.2 create_beddel_handler() returns a callable async function (AC: 1)
# ---------------------------------------------------------------------------


def test_create_beddel_handler_returns_callable(
    workflow_def: WorkflowDefinition,
    registry: PrimitiveRegistry,
) -> None:
    """create_beddel_handler() returns an async callable."""
    # Arrange & Act
    handler = create_beddel_handler(workflow_def, registry=registry)

    # Assert
    assert callable(handler)
    assert inspect.iscoroutinefunction(handler)


# ---------------------------------------------------------------------------
# 4.3 Blocking handler returns JSON with ExecutionResult shape (AC: 3)
# ---------------------------------------------------------------------------


async def test_blocking_handler_returns_json_with_execution_result(
    workflow_def: WorkflowDefinition,
    registry: PrimitiveRegistry,
    mock_result: ExecutionResult,
) -> None:
    """Handler returns JSON response matching ExecutionResult model_dump shape."""
    # Arrange
    with patch(
        "beddel.integrations.fastapi.WorkflowExecutor.execute",
        new_callable=AsyncMock,
        return_value=mock_result,
    ):
        handler = create_beddel_handler(workflow_def, registry=registry)
        app = _mount_handler(handler)

        # Act
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.post("/run", json={"prompt": "hello"})

    # Assert
    assert response.status_code == 200
    body = response.json()
    assert body["workflow_id"] == "test-123"
    assert body["success"] is True
    assert body["output"] == "Hello from Beddel!"
    # Verify ExecutionResult shape keys are present
    assert "step_results" in body
    assert "error" in body
    assert "duration_ms" in body


# ---------------------------------------------------------------------------
# 4.4 ParseError maps to HTTP 400 (AC: 6)
# ---------------------------------------------------------------------------


async def test_parse_error_maps_to_http_400(
    workflow_def: WorkflowDefinition,
    registry: PrimitiveRegistry,
) -> None:
    """ParseError during execution returns 400 with structured error JSON."""
    # Arrange
    parse_exc = ParseError(
        "Invalid YAML syntax",
        code=ErrorCode.PARSE_INVALID_YAML,
        details={"line": 5},
    )
    with patch(
        "beddel.integrations.fastapi.WorkflowExecutor.execute",
        new_callable=AsyncMock,
        side_effect=parse_exc,
    ):
        handler = create_beddel_handler(workflow_def, registry=registry)
        app = _mount_handler(handler)

        # Act
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.post("/run", json={"prompt": "hello"})

    # Assert
    assert response.status_code == 400
    body = response.json()
    assert "error" in body
    assert body["error"]["code"] == str(ErrorCode.PARSE_INVALID_YAML)
    assert "Invalid YAML syntax" in body["error"]["message"]
    assert body["error"]["details"] == {"line": 5}


async def test_configuration_error_maps_to_http_400(
    workflow_def: WorkflowDefinition,
    registry: PrimitiveRegistry,
) -> None:
    """ConfigurationError during execution returns 400 with structured error JSON."""
    # Arrange
    config_exc = ConfigurationError(
        "Missing required field",
        code=ErrorCode.CONFIG_INVALID,
        details={"field": "model"},
    )
    with patch(
        "beddel.integrations.fastapi.WorkflowExecutor.execute",
        new_callable=AsyncMock,
        side_effect=config_exc,
    ):
        handler = create_beddel_handler(workflow_def, registry=registry)
        app = _mount_handler(handler)

        # Act
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.post("/run", json={"prompt": "hello"})

    # Assert
    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == str(ErrorCode.CONFIG_INVALID)
    assert "Missing required field" in body["error"]["message"]
    assert body["error"]["details"] == {"field": "model"}


# ---------------------------------------------------------------------------
# 4.5 ExecutionError maps to HTTP 500 (AC: 6)
# ---------------------------------------------------------------------------


async def test_execution_error_maps_to_http_500(
    workflow_def: WorkflowDefinition,
    registry: PrimitiveRegistry,
) -> None:
    """ExecutionError during execution returns 500 with structured error JSON."""
    # Arrange
    exec_exc = ExecutionError(
        "Step failed",
        code=ErrorCode.EXEC_STEP_FAILED,
        details={"step_id": "step-1"},
    )
    with patch(
        "beddel.integrations.fastapi.WorkflowExecutor.execute",
        new_callable=AsyncMock,
        side_effect=exec_exc,
    ):
        handler = create_beddel_handler(workflow_def, registry=registry)
        app = _mount_handler(handler)

        # Act
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.post("/run", json={"prompt": "hello"})

    # Assert
    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == str(ErrorCode.EXEC_STEP_FAILED)
    assert "Step failed" in body["error"]["message"]
    assert body["error"]["details"] == {"step_id": "step-1"}


async def test_provider_error_maps_to_http_500(
    workflow_def: WorkflowDefinition,
    registry: PrimitiveRegistry,
) -> None:
    """ProviderError (subclass of ExecutionError) returns 500."""
    # Arrange
    provider_exc = ProviderError(
        "LLM provider timeout",
        code=ErrorCode.PROVIDER_TIMEOUT,
        details={"provider": "openai"},
    )
    with patch(
        "beddel.integrations.fastapi.WorkflowExecutor.execute",
        new_callable=AsyncMock,
        side_effect=provider_exc,
    ):
        handler = create_beddel_handler(workflow_def, registry=registry)
        app = _mount_handler(handler)

        # Act
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.post("/run", json={"prompt": "hello"})

    # Assert
    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == str(ErrorCode.PROVIDER_TIMEOUT)
    assert "LLM provider timeout" in body["error"]["message"]


async def test_generic_exception_maps_to_http_500(
    workflow_def: WorkflowDefinition,
    registry: PrimitiveRegistry,
) -> None:
    """Unexpected RuntimeError returns 500 with INTERNAL_ERROR code."""
    # Arrange
    with patch(
        "beddel.integrations.fastapi.WorkflowExecutor.execute",
        new_callable=AsyncMock,
        side_effect=RuntimeError("something unexpected"),
    ):
        handler = create_beddel_handler(workflow_def, registry=registry)
        app = _mount_handler(handler)

        # Act
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.post("/run", json={"prompt": "hello"})

    # Assert
    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "INTERNAL_ERROR"
    assert "something unexpected" in body["error"]["message"]
    assert body["error"]["details"] == {}


# ---------------------------------------------------------------------------
# 4.6 Factory accepts str path and parses YAML (AC: 2)
# ---------------------------------------------------------------------------


async def test_factory_accepts_str_path(
    registry: PrimitiveRegistry,
    mock_result: ExecutionResult,
) -> None:
    """create_beddel_handler() accepts a str YAML path and produces a working handler."""
    # Arrange — write a temp YAML file
    workflow_data = _make_yaml_data()
    with tempfile.NamedTemporaryFile(
        suffix=".yaml", mode="w", delete=False,
    ) as f:
        yaml.dump(workflow_data, f)
        yaml_path = f.name

    with patch(
        "beddel.integrations.fastapi.WorkflowExecutor.execute",
        new_callable=AsyncMock,
        return_value=mock_result,
    ):
        handler = create_beddel_handler(yaml_path, registry=registry)
        app = _mount_handler(handler)

        # Act
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.post("/run", json={"prompt": "hello"})

    # Assert
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["workflow_id"] == "test-123"


# ---------------------------------------------------------------------------
# 4.7 Factory accepts WorkflowDefinition directly (AC: 2)
# ---------------------------------------------------------------------------


async def test_factory_accepts_workflow_definition(
    workflow_def: WorkflowDefinition,
    registry: PrimitiveRegistry,
    mock_result: ExecutionResult,
) -> None:
    """create_beddel_handler() accepts a WorkflowDefinition and produces a working handler."""
    # Arrange
    with patch(
        "beddel.integrations.fastapi.WorkflowExecutor.execute",
        new_callable=AsyncMock,
        return_value=mock_result,
    ):
        handler = create_beddel_handler(workflow_def, registry=registry)
        app = _mount_handler(handler)

        # Act
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.post("/run", json={"prompt": "hello"})

    # Assert
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["output"] == "Hello from Beddel!"


# ===========================================================================
# SSE Streaming Handler Tests (Task 5)
# ===========================================================================

# ---------------------------------------------------------------------------
# SSE Helpers
# ---------------------------------------------------------------------------


async def _async_iter(items: list[str]) -> AsyncIteratorABC[str]:
    """Yield items as an async iterator (simulates streaming LLM output)."""
    for item in items:
        yield item


def _make_streaming_workflow() -> WorkflowDefinition:
    """Build a minimal streaming WorkflowDefinition (stream: true on a step)."""
    return WorkflowDefinition(
        metadata=WorkflowMetadata(name="streaming-test"),
        workflow=[
            StepDefinition(
                id="step-1",
                type="llm",
                config={"model": "gpt-4o", "stream": True},
            ),
        ],
    )


def _parse_sse_events(body: str) -> list[dict[str, str]]:
    """Parse raw SSE text into a list of ``{event, data}`` dicts.

    Handles the ``event: <type>\\r\\ndata: <payload>\\r\\n\\r\\n`` wire
    format produced by sse-starlette (which uses CRLF line endings).
    """
    events: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for raw_line in body.split("\n"):
        line = raw_line.rstrip("\r")  # strip only CR, preserve content spaces
        if line.startswith("event: "):
            current["event"] = line[len("event: "):]
        elif line.startswith("data: "):
            current["data"] = line[len("data: "):]
        elif line.startswith("data:") and line == "data:":
            # data field with empty value
            current["data"] = ""
        elif line == "" and current:
            events.append(current)
            current = {}
    if current:
        events.append(current)
    return events


# ---------------------------------------------------------------------------
# SSE Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def streaming_workflow_def() -> WorkflowDefinition:
    """Minimal streaming WorkflowDefinition (stream: true)."""
    return _make_streaming_workflow()


# ---------------------------------------------------------------------------
# 5.1 Streaming workflow returns EventSourceResponse (AC: 4)
# ---------------------------------------------------------------------------


async def test_streaming_workflow_returns_event_source_response(
    streaming_workflow_def: WorkflowDefinition,
    registry: PrimitiveRegistry,
) -> None:
    """Streaming workflow returns SSE content type (text/event-stream)."""
    # Arrange
    chunks = ["Hello", " ", "world"]
    mock_result = ExecutionResult(
        workflow_id="sse-123",
        success=True,
        output=_async_iter(chunks),
    )
    with patch(
        "beddel.integrations.fastapi.WorkflowExecutor.execute",
        new_callable=AsyncMock,
        return_value=mock_result,
    ):
        handler = create_beddel_handler(streaming_workflow_def, registry=registry)
        app = _mount_handler(handler)

        # Act
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.post("/run", json={"prompt": "hello"})

    # Assert
    assert response.status_code == 200
    content_type = response.headers.get("content-type", "")
    assert "text/event-stream" in content_type


# ---------------------------------------------------------------------------
# 5.2 SSE events follow the event: chunk / data: ... format (AC: 5)
# ---------------------------------------------------------------------------


async def test_sse_events_follow_chunk_format(
    streaming_workflow_def: WorkflowDefinition,
    registry: PrimitiveRegistry,
) -> None:
    """SSE chunk events have ``event: chunk`` and ``data: <text>`` fields."""
    # Arrange
    chunks = ["Hello", " ", "world"]
    mock_result = ExecutionResult(
        workflow_id="sse-123",
        success=True,
        output=_async_iter(chunks),
    )
    with patch(
        "beddel.integrations.fastapi.WorkflowExecutor.execute",
        new_callable=AsyncMock,
        return_value=mock_result,
    ):
        handler = create_beddel_handler(streaming_workflow_def, registry=registry)
        app = _mount_handler(handler)

        # Act
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.post("/run", json={"prompt": "hello"})

    # Assert — parse SSE events and verify chunk format
    events = _parse_sse_events(response.text)
    chunk_events = [e for e in events if e.get("event") == "chunk"]
    assert len(chunk_events) == len(chunks)
    for i, event in enumerate(chunk_events):
        assert event["event"] == "chunk"
        assert event["data"] == chunks[i]


# ---------------------------------------------------------------------------
# 5.3 [DONE] sentinel is sent on completion (AC: 5)
# ---------------------------------------------------------------------------


async def test_sse_done_sentinel_sent_on_completion(
    streaming_workflow_def: WorkflowDefinition,
    registry: PrimitiveRegistry,
) -> None:
    """The last SSE event is ``event: done`` with ``data: [DONE]``."""
    # Arrange
    chunks = ["Hello"]
    mock_result = ExecutionResult(
        workflow_id="sse-123",
        success=True,
        output=_async_iter(chunks),
    )
    with patch(
        "beddel.integrations.fastapi.WorkflowExecutor.execute",
        new_callable=AsyncMock,
        return_value=mock_result,
    ):
        handler = create_beddel_handler(streaming_workflow_def, registry=registry)
        app = _mount_handler(handler)

        # Act
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.post("/run", json={"prompt": "hello"})

    # Assert
    events = _parse_sse_events(response.text)
    assert len(events) >= 2  # at least one chunk + done
    done_event = events[-1]
    assert done_event["event"] == "done"
    assert done_event["data"] == "[DONE]"


# ---------------------------------------------------------------------------
# 5.4 Error during streaming yields event: error SSE event (AC: 5)
# ---------------------------------------------------------------------------


async def test_sse_error_event_on_execution_error(
    streaming_workflow_def: WorkflowDefinition,
    registry: PrimitiveRegistry,
) -> None:
    """ExecutionError during streaming yields an ``event: error`` SSE event."""
    # Arrange
    exec_exc = ExecutionError(
        "Step failed",
        code=ErrorCode.EXEC_STEP_FAILED,
        details={"step_id": "step-1"},
    )
    with patch(
        "beddel.integrations.fastapi.WorkflowExecutor.execute",
        new_callable=AsyncMock,
        side_effect=exec_exc,
    ):
        handler = create_beddel_handler(streaming_workflow_def, registry=registry)
        app = _mount_handler(handler)

        # Act
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.post("/run", json={"prompt": "hello"})

    # Assert — SSE stream should contain an error event
    events = _parse_sse_events(response.text)
    error_events = [e for e in events if e.get("event") == "error"]
    assert len(error_events) == 1
    error_data = json.loads(error_events[0]["data"])
    assert error_data["code"] == str(ErrorCode.EXEC_STEP_FAILED)
    assert "Step failed" in error_data["message"]
    assert error_data["details"] == {"step_id": "step-1"}


# ---------------------------------------------------------------------------
# 5.5 SSE response headers include Cache-Control: no-cache (AC: 10)
# ---------------------------------------------------------------------------


async def test_sse_response_headers_include_cache_control(
    streaming_workflow_def: WorkflowDefinition,
    registry: PrimitiveRegistry,
) -> None:
    """SSE response includes ``Cache-Control: no-cache`` header."""
    # Arrange
    chunks = ["ok"]
    mock_result = ExecutionResult(
        workflow_id="sse-123",
        success=True,
        output=_async_iter(chunks),
    )
    with patch(
        "beddel.integrations.fastapi.WorkflowExecutor.execute",
        new_callable=AsyncMock,
        return_value=mock_result,
    ):
        handler = create_beddel_handler(streaming_workflow_def, registry=registry)
        app = _mount_handler(handler)

        # Act
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.post("/run", json={"prompt": "hello"})

    # Assert
    cache_control = response.headers.get("cache-control", "")
    assert "no-cache" in cache_control


# ===========================================================================
# Import Guard Tests (Task 6)
# ===========================================================================

# ---------------------------------------------------------------------------
# 6.1 ImportError raised with helpful message when fastapi is missing (AC: 7)
# ---------------------------------------------------------------------------


def test_import_error_when_fastapi_missing() -> None:
    """ImportError with helpful message when fastapi is not installed."""
    # Arrange — remove cached module and block fastapi import
    modules_to_remove = [
        key
        for key in sys.modules
        if key.startswith("beddel.integrations.fastapi")
    ]

    saved_modules = {key: sys.modules.pop(key) for key in modules_to_remove}

    original_import = builtins.__import__

    def mock_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name in (
            "fastapi",
            "fastapi.responses",
            "sse_starlette",
            "sse_starlette.sse",
        ):
            raise ImportError(f"No module named '{name}'")
        return original_import(name, *args, **kwargs)

    try:
        # Act & Assert
        with (
            patch("builtins.__import__", side_effect=mock_import),
            pytest.raises(
                ImportError, match=r"beddel\[fastapi\] extra required"
            ),
        ):
            importlib.import_module("beddel.integrations.fastapi")
    finally:
        # Restore — put the real modules back so other tests are unaffected
        sys.modules.update(saved_modules)
