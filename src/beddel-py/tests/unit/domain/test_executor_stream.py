"""Unit tests for WorkflowExecutor.execute_stream()."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock

from beddel.domain.executor import WorkflowExecutor
from beddel.domain.models import (
    BeddelEvent,
    BeddelEventType,
    ErrorCode,
    ExecutionError,
    StepDefinition,
    WorkflowDefinition,
    WorkflowMetadata,
)
from beddel.domain.registry import PrimitiveRegistry

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_workflow(*steps: StepDefinition) -> WorkflowDefinition:
    """Build a minimal WorkflowDefinition with the given steps."""
    return WorkflowDefinition(
        metadata=WorkflowMetadata(name="test-wf"),
        workflow=list(steps),
    )


def _make_step(step_id: str, step_type: str = "llm", **kwargs: Any) -> StepDefinition:
    """Build a StepDefinition with sensible defaults."""
    return StepDefinition(id=step_id, type=step_type, **kwargs)


async def _async_iter(items: list[str]) -> AsyncIterator[str]:
    """Yield items as an async iterator."""
    for item in items:
        yield item


async def _collect_events(
    executor: WorkflowExecutor,
    workflow: WorkflowDefinition,
    input_data: dict[str, Any] | None = None,
) -> list[BeddelEvent]:
    """Collect all events from execute_stream() into a list."""
    events: list[BeddelEvent] = []
    async for event in executor.execute_stream(workflow, input_data):
        events.append(event)
    return events


def _make_registry(*primitives: tuple[str, Any]) -> PrimitiveRegistry:
    """Build a PrimitiveRegistry with mock primitives."""
    registry = PrimitiveRegistry()
    for name, fn in primitives:
        registry.register_func(name, fn)
    return registry


def _make_hook() -> AsyncMock:
    """Create a mock lifecycle hook with all required methods."""
    hook = AsyncMock()
    hook.on_workflow_start = AsyncMock()
    hook.on_step_start = AsyncMock()
    hook.on_step_end = AsyncMock()
    hook.on_workflow_end = AsyncMock()
    hook.on_error = AsyncMock()
    hook.on_llm_start = AsyncMock()
    hook.on_llm_end = AsyncMock()
    return hook


# ---------------------------------------------------------------------------
# 7.2 Event sequence for successful 2-step workflow
# ---------------------------------------------------------------------------


class TestEventSequence:
    """execute_stream() yields correct event sequence for successful workflows."""

    async def test_two_step_workflow_event_sequence(self) -> None:
        """WF_START → S1_START → S1_RESULT → S1_END → S2_START → S2_RESULT → S2_END → WF_END."""
        async def step_fn(config: dict, ctx: Any) -> str:
            return "output"

        registry = _make_registry(("llm", step_fn))
        executor = WorkflowExecutor(registry=registry)
        workflow = _make_workflow(_make_step("s1"), _make_step("s2"))

        events = await _collect_events(executor, workflow, {"prompt": "hi"})
        types = [e.type for e in events]

        assert types == [
            BeddelEventType.WORKFLOW_START,
            BeddelEventType.STEP_START,
            BeddelEventType.STEP_RESULT,
            BeddelEventType.STEP_END,
            BeddelEventType.STEP_START,
            BeddelEventType.STEP_RESULT,
            BeddelEventType.STEP_END,
            BeddelEventType.WORKFLOW_END,
        ]

    async def test_single_step_workflow(self) -> None:
        """Single-step: WF_START → S_START → S_RESULT → S_END → WF_END."""
        async def step_fn(config: dict, ctx: Any) -> str:
            return "ok"

        registry = _make_registry(("llm", step_fn))
        executor = WorkflowExecutor(registry=registry)
        workflow = _make_workflow(_make_step("s1"))

        events = await _collect_events(executor, workflow)
        types = [e.type for e in events]

        assert types == [
            BeddelEventType.WORKFLOW_START,
            BeddelEventType.STEP_START,
            BeddelEventType.STEP_RESULT,
            BeddelEventType.STEP_END,
            BeddelEventType.WORKFLOW_END,
        ]


# ---------------------------------------------------------------------------
# 7.3 STEP_START / STEP_END pairing invariant
# ---------------------------------------------------------------------------


class TestStepPairing:
    """Every STEP_START has a matching STEP_END (success path)."""

    async def test_step_start_end_pairing(self) -> None:
        """Each STEP_START has a corresponding STEP_END with the same step_id."""
        async def step_fn(config: dict, ctx: Any) -> str:
            return "ok"

        registry = _make_registry(("llm", step_fn))
        executor = WorkflowExecutor(registry=registry)
        workflow = _make_workflow(
            _make_step("a"), _make_step("b"), _make_step("c"),
        )

        events = await _collect_events(executor, workflow)
        starts = [e.step_id for e in events if e.type == BeddelEventType.STEP_START]
        ends = [e.step_id for e in events if e.type == BeddelEventType.STEP_END]

        assert starts == ends == ["a", "b", "c"]


# ---------------------------------------------------------------------------
# 7.4 WORKFLOW_START first, WORKFLOW_END last
# ---------------------------------------------------------------------------


class TestWorkflowOrdering:
    """WORKFLOW_START is always first, WORKFLOW_END is always last."""

    async def test_workflow_start_is_first(self) -> None:
        async def step_fn(config: dict, ctx: Any) -> str:
            return "ok"

        registry = _make_registry(("llm", step_fn))
        executor = WorkflowExecutor(registry=registry)
        workflow = _make_workflow(_make_step("s1"))

        events = await _collect_events(executor, workflow)
        assert events[0].type == BeddelEventType.WORKFLOW_START

    async def test_workflow_end_is_last(self) -> None:
        async def step_fn(config: dict, ctx: Any) -> str:
            return "ok"

        registry = _make_registry(("llm", step_fn))
        executor = WorkflowExecutor(registry=registry)
        workflow = _make_workflow(_make_step("s1"))

        events = await _collect_events(executor, workflow)
        assert events[-1].type == BeddelEventType.WORKFLOW_END

    async def test_workflow_start_data(self) -> None:
        """WORKFLOW_START data contains workflow_name and input_keys."""
        async def step_fn(config: dict, ctx: Any) -> str:
            return "ok"

        registry = _make_registry(("llm", step_fn))
        executor = WorkflowExecutor(registry=registry)
        workflow = _make_workflow(_make_step("s1"))

        events = await _collect_events(executor, workflow, {"prompt": "hi", "model": "gpt"})
        start_event = events[0]

        assert start_event.data["workflow_name"] == "test-wf"
        assert set(start_event.data["input_keys"]) == {"prompt", "model"}

    async def test_workflow_end_data(self) -> None:
        """WORKFLOW_END data contains success and duration_ms."""
        async def step_fn(config: dict, ctx: Any) -> str:
            return "ok"

        registry = _make_registry(("llm", step_fn))
        executor = WorkflowExecutor(registry=registry)
        workflow = _make_workflow(_make_step("s1"))

        events = await _collect_events(executor, workflow)
        end_event = events[-1]

        assert end_event.data["success"] is True
        assert "duration_ms" in end_event.data
        assert isinstance(end_event.data["duration_ms"], float)


# ---------------------------------------------------------------------------
# 7.5 Dual-write parity (hooks + events)
# ---------------------------------------------------------------------------


class TestDualWriteParity:
    """Hooks fire at the same lifecycle points as events are yielded."""

    async def test_hooks_called_in_sync_with_events(self) -> None:
        """on_workflow_start, on_step_start, on_step_end, on_workflow_end called."""
        async def step_fn(config: dict, ctx: Any) -> str:
            return "ok"

        hook = _make_hook()
        registry = _make_registry(("llm", step_fn))
        executor = WorkflowExecutor(registry=registry, hooks=[hook])
        workflow = _make_workflow(_make_step("s1"))

        await _collect_events(executor, workflow, {"prompt": "hi"})

        hook.on_workflow_start.assert_called_once()
        hook.on_step_start.assert_called_once()
        hook.on_step_end.assert_called_once()
        hook.on_workflow_end.assert_called_once()
        hook.on_error.assert_not_called()

    async def test_two_step_hooks_called_twice(self) -> None:
        """on_step_start and on_step_end called once per step."""
        async def step_fn(config: dict, ctx: Any) -> str:
            return "ok"

        hook = _make_hook()
        registry = _make_registry(("llm", step_fn))
        executor = WorkflowExecutor(registry=registry, hooks=[hook])
        workflow = _make_workflow(_make_step("s1"), _make_step("s2"))

        await _collect_events(executor, workflow)

        assert hook.on_step_start.call_count == 2
        assert hook.on_step_end.call_count == 2


# ---------------------------------------------------------------------------
# 7.6 Error mid-workflow
# ---------------------------------------------------------------------------


class TestErrorMidWorkflow:
    """Step failure yields ERROR event and stops iteration."""

    async def test_error_stops_iteration(self) -> None:
        """Second step raises → ERROR event, no WORKFLOW_END."""
        call_count = 0

        async def step_fn(config: dict, ctx: Any) -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise RuntimeError("step 2 exploded")
            return "ok"

        hook = _make_hook()
        registry = _make_registry(("llm", step_fn))
        executor = WorkflowExecutor(registry=registry, hooks=[hook])
        workflow = _make_workflow(_make_step("s1"), _make_step("s2"))

        events = await _collect_events(executor, workflow)
        types = [e.type for e in events]

        assert BeddelEventType.ERROR in types
        assert BeddelEventType.WORKFLOW_END not in types
        assert types[-1] == BeddelEventType.ERROR
        hook.on_error.assert_called_once()

    async def test_error_event_has_structured_payload(self) -> None:
        """ERROR event data has code, message, details keys."""
        async def failing_fn(config: dict, ctx: Any) -> str:
            raise RuntimeError("boom")

        registry = _make_registry(("llm", failing_fn))
        executor = WorkflowExecutor(registry=registry)
        workflow = _make_workflow(_make_step("s1"))

        events = await _collect_events(executor, workflow)
        error_event = [e for e in events if e.type == BeddelEventType.ERROR][0]

        assert set(error_event.data.keys()) == {"code", "message", "details"}

    async def test_beddel_error_preserves_code(self) -> None:
        """BeddelError subclass preserves error code in ERROR event."""
        async def failing_fn(config: dict, ctx: Any) -> str:
            raise ExecutionError(
                "timeout",
                code=ErrorCode.EXEC_TIMEOUT,
                details={"timeout_seconds": 300},
            )

        registry = _make_registry(("llm", failing_fn))
        executor = WorkflowExecutor(registry=registry)
        workflow = _make_workflow(_make_step("s1"))

        events = await _collect_events(executor, workflow)
        error_event = [e for e in events if e.type == BeddelEventType.ERROR][0]

        assert error_event.data["code"] == "BEDDEL-EXEC-003"
        assert error_event.data["details"] == {"timeout_seconds": 300}


# ---------------------------------------------------------------------------
# 7.7 No raw tracebacks in ERROR data
# ---------------------------------------------------------------------------


class TestNoTracebacks:
    """ERROR event data never contains raw Python tracebacks."""

    async def test_no_traceback_in_error_data(self) -> None:
        """ERROR event data values do not contain 'Traceback' or 'File' strings."""
        async def failing_fn(config: dict, ctx: Any) -> str:
            raise ValueError("bad value")

        registry = _make_registry(("llm", failing_fn))
        executor = WorkflowExecutor(registry=registry)
        workflow = _make_workflow(_make_step("s1"))

        events = await _collect_events(executor, workflow)
        error_event = [e for e in events if e.type == BeddelEventType.ERROR][0]

        for value in error_event.data.values():
            if isinstance(value, str):
                assert "Traceback" not in value
                assert 'File "' not in value


# ---------------------------------------------------------------------------
# 7.8 TEXT_CHUNK events for streaming output
# ---------------------------------------------------------------------------


class TestTextChunkEvents:
    """TEXT_CHUNK events are yielded when step output is AsyncIterator[str]."""

    async def test_streaming_step_yields_text_chunks(self) -> None:
        """AsyncIterator output yields TEXT_CHUNK events for each chunk."""
        async def streaming_fn(config: dict, ctx: Any) -> AsyncIterator[str]:
            return _async_iter(["Hello", " ", "world"])

        registry = _make_registry(("llm", streaming_fn))
        executor = WorkflowExecutor(registry=registry)
        workflow = _make_workflow(_make_step("s1"))

        events = await _collect_events(executor, workflow)
        chunk_events = [e for e in events if e.type == BeddelEventType.TEXT_CHUNK]

        assert len(chunk_events) == 3
        assert [e.data for e in chunk_events] == ["Hello", " ", "world"]
        assert all(e.step_id == "s1" for e in chunk_events)

    async def test_streaming_step_event_sequence(self) -> None:
        """Streaming step: STEP_START → TEXT_CHUNK* → STEP_RESULT → STEP_END."""
        async def streaming_fn(config: dict, ctx: Any) -> AsyncIterator[str]:
            return _async_iter(["a", "b"])

        registry = _make_registry(("llm", streaming_fn))
        executor = WorkflowExecutor(registry=registry)
        workflow = _make_workflow(_make_step("s1"))

        events = await _collect_events(executor, workflow)
        step_types = [e.type for e in events if e.step_id == "s1"]

        assert step_types == [
            BeddelEventType.STEP_START,
            BeddelEventType.TEXT_CHUNK,
            BeddelEventType.TEXT_CHUNK,
            BeddelEventType.STEP_RESULT,
            BeddelEventType.STEP_END,
        ]


# ---------------------------------------------------------------------------
# 7.9 GeneratorExit handling
# ---------------------------------------------------------------------------


class TestGeneratorExit:
    """GeneratorExit is handled gracefully."""

    async def test_generator_exit_logs_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        """Closing the generator mid-iteration logs a warning."""
        async def slow_fn(config: dict, ctx: Any) -> str:
            return "ok"

        registry = _make_registry(("llm", slow_fn))
        executor = WorkflowExecutor(registry=registry)
        workflow = _make_workflow(_make_step("s1"), _make_step("s2"))

        with caplog.at_level(logging.WARNING, logger="beddel.executor"):
            gen = executor.execute_stream(workflow)
            event = await gen.__anext__()
            assert event.type == BeddelEventType.WORKFLOW_START
            await gen.aclose()

        assert "Client disconnected" in caplog.text

    async def test_generator_exit_no_exception(self) -> None:
        """Closing the generator does not raise any exception."""
        async def step_fn(config: dict, ctx: Any) -> str:
            return "ok"

        registry = _make_registry(("llm", step_fn))
        executor = WorkflowExecutor(registry=registry)
        workflow = _make_workflow(_make_step("s1"))

        gen = executor.execute_stream(workflow)
        await gen.__anext__()  # WORKFLOW_START
        await gen.aclose()  # Should not raise


# ---------------------------------------------------------------------------
# 7.10 Conditional step skip
# ---------------------------------------------------------------------------


class TestConditionalStepSkip:
    """Step with falsy condition yields no events for that step."""

    async def test_skipped_step_no_events(self) -> None:
        """Step with condition='false' produces no STEP_START/STEP_END events."""
        async def step_fn(config: dict, ctx: Any) -> str:
            return "ok"

        registry = _make_registry(("llm", step_fn))
        executor = WorkflowExecutor(registry=registry)
        workflow = _make_workflow(
            _make_step("s1"),
            _make_step("s2", condition="false"),
            _make_step("s3"),
        )

        events = await _collect_events(executor, workflow)
        step_ids = [e.step_id for e in events if e.step_id is not None]

        assert "s2" not in step_ids
        assert "s1" in step_ids
        assert "s3" in step_ids

    async def test_skipped_step_event_count(self) -> None:
        """Skipping a step reduces total event count."""
        async def step_fn(config: dict, ctx: Any) -> str:
            return "ok"

        registry = _make_registry(("llm", step_fn))
        executor = WorkflowExecutor(registry=registry)
        workflow = _make_workflow(
            _make_step("s1"),
            _make_step("s2", condition="false"),
            _make_step("s3"),
        )

        events = await _collect_events(executor, workflow)
        types = [e.type for e in events]

        # WF_START, S1_START, S1_RESULT, S1_END, S3_START, S3_RESULT, S3_END, WF_END
        assert len(types) == 8
        assert types.count(BeddelEventType.STEP_START) == 2
        assert types.count(BeddelEventType.STEP_END) == 2
