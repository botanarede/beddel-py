"""Unit tests for DashboardSSEBridge (Story D1.3, Task 3)."""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from typing import Any

from beddel.domain.models import BeddelEvent, EventType, Step, Workflow
from beddel.integrations.dashboard.bridge import DashboardSSEBridge
from beddel.integrations.dashboard.history import ExecutionHistoryStore

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_workflow(wf_id: str = "wf-1", name: str = "Test WF") -> Workflow:
    """Create a minimal Workflow for testing."""
    return Workflow(
        id=wf_id,
        name=name,
        steps=[Step(id="s1", primitive="llm", config={"model": "gpt-4"})],
    )


def _make_events() -> list[BeddelEvent]:
    """Create a small list of BeddelEvent objects for testing."""
    return [
        BeddelEvent(event_type=EventType.WORKFLOW_START, data={"workflow_id": "wf-1"}),
        BeddelEvent(event_type=EventType.STEP_START, step_id="s1", data={"primitive": "llm"}),
        BeddelEvent(event_type=EventType.STEP_END, step_id="s1", data={"result": "ok"}),
        BeddelEvent(event_type=EventType.WORKFLOW_END, data={"workflow_id": "wf-1"}),
    ]


class MockExecutor:
    """Minimal mock that implements execute_stream."""

    def __init__(self, events: list[BeddelEvent]) -> None:
        self._events = events

    async def execute_stream(
        self,
        workflow: Workflow,
        inputs: dict[str, Any] | None = None,
        *,
        execution_strategy: Any = None,
    ) -> AsyncGenerator[BeddelEvent, None]:
        for event in self._events:
            yield event


class ErrorExecutor:
    """Mock executor that raises during streaming."""

    async def execute_stream(
        self,
        workflow: Workflow,
        inputs: dict[str, Any] | None = None,
        *,
        execution_strategy: Any = None,
    ) -> AsyncGenerator[BeddelEvent, None]:
        yield BeddelEvent(event_type=EventType.WORKFLOW_START, data={"workflow_id": workflow.id})
        raise RuntimeError("executor boom")
        # Make this a generator
        yield  # pragma: no cover


# ---------------------------------------------------------------------------
# DashboardSSEBridge tests
# ---------------------------------------------------------------------------


class TestDashboardSSEBridge:
    """Tests for DashboardSSEBridge.execute_and_stream()."""

    async def test_returns_valid_uuid_and_stream(self) -> None:
        """execute_and_stream returns a valid UUID run_id and an async generator."""
        executor = MockExecutor(_make_events())
        history = ExecutionHistoryStore()
        bridge = DashboardSSEBridge(executor=executor, history=history)  # type: ignore[arg-type]

        run_id, stream = await bridge.execute_and_stream(_make_workflow())

        # run_id should be a valid UUID4
        parsed = uuid.UUID(run_id, version=4)
        assert str(parsed) == run_id

        # stream should be an async generator
        assert hasattr(stream, "__aiter__")
        # Consume to avoid warnings
        async for _ in stream:
            pass

    async def test_seeds_running_record_immediately(self) -> None:
        """History store has a 'running' record before stream is consumed."""
        executor = MockExecutor(_make_events())
        history = ExecutionHistoryStore()
        bridge = DashboardSSEBridge(executor=executor, history=history)  # type: ignore[arg-type]

        run_id, stream = await bridge.execute_and_stream(_make_workflow())

        record = history.get(run_id)
        assert record is not None
        assert record.status == "running"
        assert record.workflow_id == "wf-1"
        assert record.finished_at is None

        # Consume to avoid warnings
        async for _ in stream:
            pass

    async def test_yields_sse_dicts(self) -> None:
        """Stream yields SSE-formatted dicts with 'event' and 'data' keys."""
        executor = MockExecutor(_make_events())
        history = ExecutionHistoryStore()
        bridge = DashboardSSEBridge(executor=executor, history=history)  # type: ignore[arg-type]

        _, stream = await bridge.execute_and_stream(_make_workflow())

        sse_dicts: list[dict[str, str]] = []
        async for sse_dict in stream:
            sse_dicts.append(sse_dict)

        assert len(sse_dicts) == 4
        # Each dict should have 'event' and 'data' keys
        for d in sse_dicts:
            assert "event" in d
            assert "data" in d
        # First event should be workflow_start
        assert sse_dicts[0]["event"] == "workflow_start"
        assert sse_dicts[-1]["event"] == "workflow_end"

    async def test_history_updated_on_completion(self) -> None:
        """After consuming the stream, history record is updated with success."""
        executor = MockExecutor(_make_events())
        history = ExecutionHistoryStore()
        bridge = DashboardSSEBridge(executor=executor, history=history)  # type: ignore[arg-type]

        run_id, stream = await bridge.execute_and_stream(_make_workflow())

        # Consume the stream fully
        collected: list[dict[str, str]] = []
        async for sse_dict in stream:
            collected.append(sse_dict)

        record = history.get(run_id)
        assert record is not None
        assert record.status == "success"
        assert record.finished_at is not None
        assert record.total_duration is not None
        assert record.total_duration >= 0
        assert len(record.events) == 4

    async def test_error_sets_error_status(self) -> None:
        """When executor raises, history record status is 'error'."""
        executor = ErrorExecutor()
        history = ExecutionHistoryStore()
        bridge = DashboardSSEBridge(executor=executor, history=history)  # type: ignore[arg-type]

        run_id, stream = await bridge.execute_and_stream(_make_workflow())

        # The SSE adapter catches exceptions and emits error + done events
        sse_dicts: list[dict[str, str]] = []
        async for sse_dict in stream:
            sse_dicts.append(sse_dict)

        # Should have at least the workflow_start event, then error + done
        assert any(d["event"] == "error" for d in sse_dicts)

        record = history.get(run_id)
        assert record is not None
        assert record.status == "error"
        assert record.finished_at is not None

    async def test_events_collected_in_history(self) -> None:
        """All SSE dicts are collected into the history record's events list."""
        executor = MockExecutor(_make_events())
        history = ExecutionHistoryStore()
        bridge = DashboardSSEBridge(executor=executor, history=history)  # type: ignore[arg-type]

        run_id, stream = await bridge.execute_and_stream(_make_workflow())

        yielded: list[dict[str, str]] = []
        async for sse_dict in stream:
            yielded.append(sse_dict)

        record = history.get(run_id)
        assert record is not None
        # The events stored should match what was yielded
        assert record.events == yielded

    async def test_passes_inputs_to_executor(self) -> None:
        """Inputs are forwarded to the executor's execute_stream."""
        received_inputs: list[Any] = []

        class CapturingExecutor:
            async def execute_stream(
                self,
                workflow: Workflow,
                inputs: dict[str, Any] | None = None,
                *,
                execution_strategy: Any = None,
            ) -> AsyncGenerator[BeddelEvent, None]:
                received_inputs.append(inputs)
                yield BeddelEvent(event_type=EventType.WORKFLOW_END, data={})

        executor = CapturingExecutor()
        history = ExecutionHistoryStore()
        bridge = DashboardSSEBridge(executor=executor, history=history)  # type: ignore[arg-type]

        _, stream = await bridge.execute_and_stream(_make_workflow(), inputs={"key": "value"})
        async for _ in stream:
            pass

        assert received_inputs == [{"key": "value"}]
