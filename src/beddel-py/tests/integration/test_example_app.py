"""Smoke tests for the example FastAPI application.

Ensures the example app at ``examples/fastapi_app.py`` remains importable
and its endpoints respond correctly — preventing bit-rot as the SDK evolves.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from examples.fastapi_app import app
from httpx import ASGITransport, AsyncClient

from beddel.domain.models import ExecutionResult

# ---------------------------------------------------------------------------
# 4.3 GET /health returns 200 with {"status": "ok"} (AC: 9)
# ---------------------------------------------------------------------------


async def test_health_endpoint_returns_ok() -> None:
    """GET /health returns 200 with a simple status payload."""
    # Arrange
    transport = ASGITransport(app=app)

    # Act
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")

    # Assert
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# 4.4 POST /agent/simple is reachable with mocked executor (AC: 9)
# ---------------------------------------------------------------------------


async def test_simple_endpoint_is_reachable() -> None:
    """POST /agent/simple returns a valid response when the executor is mocked."""
    # Arrange
    mock_result = ExecutionResult(
        workflow_id="smoke-test-123",
        success=True,
        output={"greeting": "Hello!"},
        step_results={},
        duration_ms=0.0,
    )
    transport = ASGITransport(app=app)

    # Act
    with patch(
        "beddel.domain.executor.WorkflowExecutor.execute",
        new_callable=AsyncMock,
        return_value=mock_result,
    ):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/agent/simple", json={"prompt": "Hello"})

    # Assert
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["workflow_id"] == "smoke-test-123"
    assert body["output"] == {"greeting": "Hello!"}
