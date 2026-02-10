"""Unit tests for the LifecycleHooksAdapter."""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from beddel.adapters.hooks import LifecycleHooksAdapter
from beddel.domain.models import (
    LLMRequest,
    LLMResponse,
    Message,
    StepDefinition,
    TokenUsage,
    WorkflowDefinition,
    WorkflowMetadata,
)
from beddel.domain.ports import ILifecycleHook

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_llm_request() -> LLMRequest:
    """Build a minimal LLMRequest for testing."""
    return LLMRequest(
        model="gpt-4o-mini",
        messages=[Message(role="user", content="Hello")],
    )


def _make_llm_response() -> LLMResponse:
    """Build a minimal LLMResponse for testing."""
    return LLMResponse(
        content="Hi",
        model="gpt-4o-mini",
        usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
    )


def _make_step() -> StepDefinition:
    """Build a minimal StepDefinition for testing."""
    return StepDefinition(id="step-1", type="llm")


def _make_workflow() -> WorkflowDefinition:
    """Build a minimal WorkflowDefinition for testing."""
    return WorkflowDefinition(metadata=WorkflowMetadata(name="test"), workflow=[])


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def adapter() -> LifecycleHooksAdapter:
    """Fresh LifecycleHooksAdapter instance."""
    return LifecycleHooksAdapter()


# ---------------------------------------------------------------------------
# 5.2 register() adds callbacks and emit() dispatches to them (AC: 2, 3)
# ---------------------------------------------------------------------------


async def test_register_adds_callback_and_emit_dispatches(
    adapter: LifecycleHooksAdapter,
) -> None:
    """register() stores callback; emit() invokes it with correct kwargs."""
    # Arrange
    callback = AsyncMock()
    adapter.register("on_step_start", callback)

    # Act
    step = _make_step()
    await adapter.emit("on_step_start", step=step)

    # Assert
    callback.assert_awaited_once_with(step=step)


async def test_register_multiple_callbacks_all_dispatched(
    adapter: LifecycleHooksAdapter,
) -> None:
    """Multiple callbacks registered for the same event are all dispatched."""
    # Arrange
    cb1 = AsyncMock()
    cb2 = AsyncMock()
    adapter.register("on_error", cb1)
    adapter.register("on_error", cb2)

    # Act
    error = RuntimeError("boom")
    await adapter.emit("on_error", error=error)

    # Assert
    cb1.assert_awaited_once_with(error=error)
    cb2.assert_awaited_once_with(error=error)


async def test_emit_no_listeners_does_nothing(
    adapter: LifecycleHooksAdapter,
) -> None:
    """emit() with no registered listeners completes without error."""
    # Act & Assert — should not raise
    await adapter.emit("on_workflow_start", workflow=_make_workflow(), input_data={})


# ---------------------------------------------------------------------------
# 5.3 emit() with async callback (AC: 7)
# ---------------------------------------------------------------------------


async def test_emit_async_callback_is_awaited(
    adapter: LifecycleHooksAdapter,
) -> None:
    """emit() awaits async callbacks."""
    # Arrange
    call_log: list[str] = []

    async def async_cb(**kwargs: Any) -> None:
        call_log.append("async_called")

    adapter.register("on_step_end", async_cb)

    # Act
    await adapter.emit("on_step_end", step=_make_step(), result="ok")

    # Assert
    assert call_log == ["async_called"]


# ---------------------------------------------------------------------------
# 5.4 emit() with sync callback (auto-wrapped) (AC: 7)
# ---------------------------------------------------------------------------


async def test_emit_sync_callback_is_called_directly(
    adapter: LifecycleHooksAdapter,
) -> None:
    """emit() calls sync callbacks directly (no await)."""
    # Arrange
    call_log: list[str] = []

    def sync_cb(**kwargs: Any) -> None:
        call_log.append("sync_called")

    adapter.register("on_step_start", sync_cb)

    # Act
    await adapter.emit("on_step_start", step=_make_step())

    # Assert
    assert call_log == ["sync_called"]


async def test_emit_mixed_sync_and_async_callbacks(
    adapter: LifecycleHooksAdapter,
) -> None:
    """emit() handles a mix of sync and async callbacks in order."""
    # Arrange
    call_order: list[str] = []

    def sync_cb(**kwargs: Any) -> None:
        call_order.append("sync")

    async def async_cb(**kwargs: Any) -> None:
        call_order.append("async")

    adapter.register("on_error", sync_cb)
    adapter.register("on_error", async_cb)

    # Act
    await adapter.emit("on_error", error=RuntimeError("test"))

    # Assert
    assert call_order == ["sync", "async"]


# ---------------------------------------------------------------------------
# 5.5 Callback exception is caught and logged, does not propagate (AC: 10)
# ---------------------------------------------------------------------------


async def test_callback_exception_caught_and_logged(
    adapter: LifecycleHooksAdapter,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Exception in callback is caught, logged as WARNING, does not propagate."""
    # Arrange
    def bad_cb(**kwargs: Any) -> None:
        msg = "callback exploded"
        raise ValueError(msg)

    adapter.register("on_step_start", bad_cb)

    # Act
    with caplog.at_level(logging.WARNING, logger="beddel.adapters.hooks"):
        await adapter.emit("on_step_start", step=_make_step())

    # Assert — no exception propagated, warning logged
    assert len(caplog.records) == 1
    assert caplog.records[0].levelno == logging.WARNING
    assert "on_step_start" in caplog.records[0].message
    assert "callback exploded" in caplog.records[0].message


async def test_exception_in_one_callback_does_not_block_others(
    adapter: LifecycleHooksAdapter,
) -> None:
    """A failing callback does not prevent subsequent callbacks from running."""
    # Arrange
    call_log: list[str] = []

    def bad_cb(**kwargs: Any) -> None:
        call_log.append("bad")
        msg = "fail"
        raise RuntimeError(msg)

    def good_cb(**kwargs: Any) -> None:
        call_log.append("good")

    adapter.register("on_error", bad_cb)
    adapter.register("on_error", good_cb)

    # Act
    await adapter.emit("on_error", error=RuntimeError("test"))

    # Assert — both callbacks ran
    assert call_log == ["bad", "good"]


async def test_async_callback_exception_caught_and_logged(
    adapter: LifecycleHooksAdapter,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Exception in async callback is also caught and logged."""
    # Arrange
    async def bad_async_cb(**kwargs: Any) -> None:
        msg = "async boom"
        raise TypeError(msg)

    adapter.register("on_llm_start", bad_async_cb)

    # Act
    with caplog.at_level(logging.WARNING, logger="beddel.adapters.hooks"):
        await adapter.emit("on_llm_start", request=_make_llm_request())

    # Assert
    assert len(caplog.records) == 1
    assert "on_llm_start" in caplog.records[0].message
    assert "async boom" in caplog.records[0].message


# ---------------------------------------------------------------------------
# 5.6 All ILifecycleHook protocol methods delegate to emit() (AC: 1, 4)
# ---------------------------------------------------------------------------


async def test_on_workflow_start_delegates_to_emit(
    adapter: LifecycleHooksAdapter,
) -> None:
    """on_workflow_start() delegates to emit() with correct event and kwargs."""
    # Arrange
    workflow = _make_workflow()
    input_data: dict[str, Any] = {"key": "value"}

    with patch.object(adapter, "emit", new_callable=AsyncMock) as mock_emit:
        # Act
        await adapter.on_workflow_start(workflow, input_data)

        # Assert
        mock_emit.assert_awaited_once_with(
            "on_workflow_start", workflow=workflow, input_data=input_data,
        )


async def test_on_step_start_delegates_to_emit(
    adapter: LifecycleHooksAdapter,
) -> None:
    """on_step_start() delegates to emit() with correct event and kwargs."""
    # Arrange
    step = _make_step()

    with patch.object(adapter, "emit", new_callable=AsyncMock) as mock_emit:
        # Act
        await adapter.on_step_start(step)

        # Assert
        mock_emit.assert_awaited_once_with("on_step_start", step=step)


async def test_on_step_end_delegates_to_emit(
    adapter: LifecycleHooksAdapter,
) -> None:
    """on_step_end() delegates to emit() with correct event and kwargs."""
    # Arrange
    step = _make_step()
    result = {"output": "done"}

    with patch.object(adapter, "emit", new_callable=AsyncMock) as mock_emit:
        # Act
        await adapter.on_step_end(step, result)

        # Assert
        mock_emit.assert_awaited_once_with("on_step_end", step=step, result=result)


async def test_on_workflow_end_delegates_to_emit(
    adapter: LifecycleHooksAdapter,
) -> None:
    """on_workflow_end() delegates to emit() with correct event and kwargs."""
    # Arrange
    workflow = _make_workflow()
    result = {"final": "output"}

    with patch.object(adapter, "emit", new_callable=AsyncMock) as mock_emit:
        # Act
        await adapter.on_workflow_end(workflow, result)

        # Assert
        mock_emit.assert_awaited_once_with(
            "on_workflow_end", workflow=workflow, result=result,
        )


async def test_on_error_delegates_to_emit(
    adapter: LifecycleHooksAdapter,
) -> None:
    """on_error() delegates to emit() with correct event and kwargs."""
    # Arrange
    error = RuntimeError("something went wrong")

    with patch.object(adapter, "emit", new_callable=AsyncMock) as mock_emit:
        # Act
        await adapter.on_error(error)

        # Assert
        mock_emit.assert_awaited_once_with("on_error", error=error)


async def test_on_llm_start_delegates_to_emit(
    adapter: LifecycleHooksAdapter,
) -> None:
    """on_llm_start() delegates to emit() with correct event and kwargs."""
    # Arrange
    request = _make_llm_request()

    with patch.object(adapter, "emit", new_callable=AsyncMock) as mock_emit:
        # Act
        await adapter.on_llm_start(request)

        # Assert
        mock_emit.assert_awaited_once_with("on_llm_start", request=request)


async def test_on_llm_end_delegates_to_emit(
    adapter: LifecycleHooksAdapter,
) -> None:
    """on_llm_end() delegates to emit() with correct event and kwargs."""
    # Arrange
    request = _make_llm_request()
    response = _make_llm_response()

    with patch.object(adapter, "emit", new_callable=AsyncMock) as mock_emit:
        # Act
        await adapter.on_llm_end(request, response)

        # Assert
        mock_emit.assert_awaited_once_with(
            "on_llm_end", request=request, response=response,
        )


# ---------------------------------------------------------------------------
# 5.7 isinstance(LifecycleHooksAdapter(), ILifecycleHook) returns True (AC: 1)
# ---------------------------------------------------------------------------


def test_adapter_satisfies_ilifecyclehook_protocol() -> None:
    """LifecycleHooksAdapter is a runtime-checkable ILifecycleHook."""
    adapter = LifecycleHooksAdapter()
    assert isinstance(adapter, ILifecycleHook)


# ---------------------------------------------------------------------------
# 5.8 on_llm_start and on_llm_end events dispatched correctly (AC: 4, 5)
# ---------------------------------------------------------------------------


async def test_on_llm_start_dispatches_to_registered_callback(
    adapter: LifecycleHooksAdapter,
) -> None:
    """on_llm_start() dispatches LLMRequest to registered callback."""
    # Arrange
    callback = AsyncMock()
    adapter.register("on_llm_start", callback)
    request = _make_llm_request()

    # Act
    await adapter.on_llm_start(request)

    # Assert
    callback.assert_awaited_once_with(request=request)


async def test_on_llm_end_dispatches_to_registered_callback(
    adapter: LifecycleHooksAdapter,
) -> None:
    """on_llm_end() dispatches LLMRequest and LLMResponse to registered callback."""
    # Arrange
    callback = AsyncMock()
    adapter.register("on_llm_end", callback)
    request = _make_llm_request()
    response = _make_llm_response()

    # Act
    await adapter.on_llm_end(request, response)

    # Assert
    callback.assert_awaited_once_with(request=request, response=response)


async def test_on_llm_start_callback_receives_correct_model(
    adapter: LifecycleHooksAdapter,
) -> None:
    """on_llm_start callback receives LLMRequest with expected model field."""
    # Arrange
    received: list[LLMRequest] = []

    async def capture_cb(**kwargs: Any) -> None:
        received.append(kwargs["request"])

    adapter.register("on_llm_start", capture_cb)
    request = _make_llm_request()

    # Act
    await adapter.on_llm_start(request)

    # Assert
    assert len(received) == 1
    assert received[0].model == "gpt-4o-mini"
    assert received[0].messages[0].content == "Hello"


async def test_on_llm_end_callback_receives_correct_usage(
    adapter: LifecycleHooksAdapter,
) -> None:
    """on_llm_end callback receives LLMResponse with expected usage data."""
    # Arrange
    received_responses: list[LLMResponse] = []

    async def capture_cb(**kwargs: Any) -> None:
        received_responses.append(kwargs["response"])

    adapter.register("on_llm_end", capture_cb)
    request = _make_llm_request()
    response = _make_llm_response()

    # Act
    await adapter.on_llm_end(request, response)

    # Assert
    assert len(received_responses) == 1
    assert received_responses[0].content == "Hi"
    assert received_responses[0].usage.total_tokens == 15
