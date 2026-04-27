"""Unit tests for beddel.adapters.a2a_server module.

Tests cover:
    - ``build_agent_card``: Agent Card generation from mock workflows.
    - ``BeddelA2AExecutor.execute``: Event mapping with mock workflow executor.
    - ``BeddelA2AExecutor.cancel``: Task cancellation.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import MagicMock

import pytest
from a2a.server.events import EventQueue
from a2a.types import DataPart, Message, Role, TextPart

from beddel.adapters.a2a_server import (
    BeddelA2AExecutor,
    WorkflowRegistry,
    build_agent_card,
)
from beddel.domain.models import (
    BeddelEvent,
    EventType,
    ExecutionStrategy,
    Step,
    StrategyType,
    Workflow,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_step(step_id: str = "step-1", primitive: str = "llm") -> Step:
    """Create a minimal Step for testing."""
    return Step(
        id=step_id,
        primitive=primitive,
        config={},
        execution_strategy=ExecutionStrategy(type=StrategyType.FAIL),
    )


def _make_workflow(
    wf_id: str = "wf-test",
    name: str = "Test Workflow",
    description: str = "A test workflow",
    steps: list[Step] | None = None,
) -> Workflow:
    """Create a minimal Workflow for testing."""
    return Workflow(
        id=wf_id,
        name=name,
        description=description,
        steps=steps or [_make_step()],
    )


def _make_request_context(
    workflow_id: str = "wf-test",
    inputs: dict[str, Any] | None = None,
    task_id: str | None = None,
    context_id: str | None = None,
) -> MagicMock:
    """Build a mock RequestContext with DataPart-based message."""
    ctx = MagicMock()
    ctx.task_id = task_id or str(uuid.uuid4())
    ctx.context_id = context_id or str(uuid.uuid4())

    data: dict[str, Any] = {"workflow_id": workflow_id}
    if inputs is not None:
        data["inputs"] = inputs

    ctx.message = Message(
        role=Role.user,
        parts=[DataPart(data=data)],
        message_id=str(uuid.uuid4()),
    )
    return ctx


# ---------------------------------------------------------------------------
# build_agent_card tests (Task 3)
# ---------------------------------------------------------------------------


class TestBuildAgentCard:
    """Tests for :func:`build_agent_card`."""

    def test_empty_workflows(self) -> None:
        """Card with no workflows has empty skills list."""
        card = build_agent_card({})
        assert card.name == "Beddel Agent"
        assert card.skills == []
        assert card.capabilities is not None
        assert card.capabilities.streaming is True

    def test_single_workflow_becomes_skill(self) -> None:
        """A single workflow maps to one AgentSkill."""
        wf = _make_workflow(wf_id="my-wf", name="My Workflow", description="Does stuff")
        registry: dict[str, tuple[Workflow, Any]] = {"my-wf": (wf, MagicMock())}

        card = build_agent_card(registry)

        assert len(card.skills) == 1
        skill = card.skills[0]
        assert skill.id == "my-wf"
        assert skill.name == "My Workflow"
        assert skill.description == "Does stuff"
        assert "workflow" in skill.tags
        assert "llm" in skill.tags  # first step primitive

    def test_multiple_workflows(self) -> None:
        """Multiple workflows produce multiple skills."""
        wf1 = _make_workflow(wf_id="wf-a", name="Alpha", steps=[_make_step(primitive="llm")])
        wf2 = _make_workflow(wf_id="wf-b", name="Beta", steps=[_make_step(primitive="tool")])
        registry: dict[str, tuple[Workflow, Any]] = {
            "wf-a": (wf1, MagicMock()),
            "wf-b": (wf2, MagicMock()),
        }

        card = build_agent_card(registry, host="0.0.0.0", port=9000)

        assert len(card.skills) == 2
        assert card.url == "http://0.0.0.0:9000"
        ids = {s.id for s in card.skills}
        assert ids == {"wf-a", "wf-b"}

    def test_workflow_without_description_gets_default(self) -> None:
        """Workflow with empty description gets a generated one."""
        wf = _make_workflow(wf_id="wf-x", name="X Flow", description="")
        registry: dict[str, tuple[Workflow, Any]] = {"wf-x": (wf, MagicMock())}

        card = build_agent_card(registry)
        skill = card.skills[0]
        assert "Execute workflow: X Flow" in skill.description

    def test_card_metadata(self) -> None:
        """Card has correct version and output modes."""
        card = build_agent_card({})
        assert card.version == "1.0.0"
        assert "application/json" in card.default_input_modes
        assert "application/json" in card.default_output_modes


# ---------------------------------------------------------------------------
# BeddelA2AExecutor tests (Task 2)
# ---------------------------------------------------------------------------


async def _mock_execute_stream(
    events: list[BeddelEvent],
) -> AsyncGenerator[BeddelEvent, None]:
    """Yield a pre-built list of BeddelEvents as an async generator."""
    for event in events:
        yield event


def _collect_events(eq: EventQueue) -> list[Any]:
    """Drain all events from an EventQueue (non-blocking).

    Accesses the underlying ``asyncio.Queue`` directly via ``get_nowait()``
    to avoid calling the async ``dequeue_event`` method.  This is the
    standard Python pattern for synchronously draining an asyncio queue
    and matches how the upstream a2a-sdk tests access ``event_queue.queue``.

    The previous implementation called ``eq.dequeue_event(no_wait=True)``
    **without** ``await``, which returned a coroutine object (always truthy,
    never raises) instead of the actual event — causing an infinite loop
    that pinned the CPU and exhausted memory.
    """
    collected: list[Any] = []
    while True:
        try:
            ev = eq.queue.get_nowait()
            collected.append(ev)
        except asyncio.QueueEmpty:
            break
    return collected


class TestBeddelA2AExecutor:
    """Tests for :class:`BeddelA2AExecutor`."""

    @pytest.mark.asyncio
    async def test_execute_happy_path(self) -> None:
        """Full workflow lifecycle emits correct A2A events."""
        wf = _make_workflow()
        mock_executor = MagicMock()

        events = [
            BeddelEvent(event_type=EventType.WORKFLOW_START, data={"workflow_id": "wf-test"}),
            BeddelEvent(
                event_type=EventType.STEP_START,
                step_id="step-1",
                data={"primitive": "llm"},
            ),
            BeddelEvent(
                event_type=EventType.TEXT_CHUNK,
                step_id="step-1",
                data={"chunk": "Hello "},
            ),
            BeddelEvent(
                event_type=EventType.STEP_END,
                step_id="step-1",
                data={"result": "Hello World"},
            ),
            BeddelEvent(event_type=EventType.WORKFLOW_END, data={"workflow_id": "wf-test"}),
        ]
        mock_executor.execute_stream = MagicMock(
            return_value=_mock_execute_stream(events),
        )

        registry: WorkflowRegistry = {"wf-test": (wf, mock_executor)}
        executor = BeddelA2AExecutor(registry)

        ctx = _make_request_context(workflow_id="wf-test")
        eq = EventQueue()

        await executor.execute(ctx, eq)

        # Verify execute_stream was called with the workflow and None inputs
        mock_executor.execute_stream.assert_called_once_with(wf, None)

        # Drain events and verify lifecycle
        collected = _collect_events(eq)
        assert len(collected) >= 4  # status updates + artifacts + completion

    @pytest.mark.asyncio
    async def test_execute_missing_workflow_id(self) -> None:
        """Missing workflow_id in message triggers failed status."""
        registry: WorkflowRegistry = {}
        executor = BeddelA2AExecutor(registry)

        ctx = MagicMock()
        ctx.task_id = str(uuid.uuid4())
        ctx.context_id = str(uuid.uuid4())
        # Message with no DataPart containing workflow_id
        ctx.message = Message(
            role=Role.user,
            parts=[TextPart(text="just text")],
            message_id=str(uuid.uuid4()),
        )

        eq = EventQueue()
        await executor.execute(ctx, eq)

        collected = _collect_events(eq)
        # Should have a failed status event
        assert len(collected) >= 1

    @pytest.mark.asyncio
    async def test_execute_unknown_workflow(self) -> None:
        """Unknown workflow_id triggers failed status."""
        registry: WorkflowRegistry = {}
        executor = BeddelA2AExecutor(registry)

        ctx = _make_request_context(workflow_id="nonexistent")
        eq = EventQueue()

        await executor.execute(ctx, eq)

        collected = _collect_events(eq)
        assert len(collected) >= 1

    @pytest.mark.asyncio
    async def test_execute_with_inputs(self) -> None:
        """Inputs from DataPart are forwarded to execute_stream."""
        wf = _make_workflow()
        mock_executor = MagicMock()

        events = [
            BeddelEvent(event_type=EventType.WORKFLOW_START, data={}),
            BeddelEvent(event_type=EventType.WORKFLOW_END, data={}),
        ]
        mock_executor.execute_stream = MagicMock(
            return_value=_mock_execute_stream(events),
        )

        registry: WorkflowRegistry = {"wf-test": (wf, mock_executor)}
        executor = BeddelA2AExecutor(registry)

        ctx = _make_request_context(
            workflow_id="wf-test",
            inputs={"topic": "AI agents"},
        )
        eq = EventQueue()

        await executor.execute(ctx, eq)

        mock_executor.execute_stream.assert_called_once_with(wf, {"topic": "AI agents"})

    @pytest.mark.asyncio
    async def test_execute_error_event(self) -> None:
        """ERROR event maps to updater.failed()."""
        wf = _make_workflow()
        mock_executor = MagicMock()

        events = [
            BeddelEvent(event_type=EventType.WORKFLOW_START, data={}),
            BeddelEvent(
                event_type=EventType.ERROR,
                step_id="step-1",
                data={"error": "LLM timeout"},
            ),
        ]
        mock_executor.execute_stream = MagicMock(
            return_value=_mock_execute_stream(events),
        )

        registry: WorkflowRegistry = {"wf-test": (wf, mock_executor)}
        executor = BeddelA2AExecutor(registry)

        ctx = _make_request_context(workflow_id="wf-test")
        eq = EventQueue()

        await executor.execute(ctx, eq)

        collected = _collect_events(eq)
        # Should have start_work + failed events
        assert len(collected) >= 2

    @pytest.mark.asyncio
    async def test_execute_exception_in_stream(self) -> None:
        """Exception during streaming maps to updater.failed()."""
        wf = _make_workflow()
        mock_executor = MagicMock()

        async def _failing_stream(_wf: Any, _inputs: Any) -> AsyncGenerator[BeddelEvent, None]:
            yield BeddelEvent(event_type=EventType.WORKFLOW_START, data={})
            raise RuntimeError("boom")

        mock_executor.execute_stream = MagicMock(
            side_effect=lambda wf, inputs: _failing_stream(wf, inputs),
        )

        registry: WorkflowRegistry = {"wf-test": (wf, mock_executor)}
        executor = BeddelA2AExecutor(registry)

        ctx = _make_request_context(workflow_id="wf-test")
        eq = EventQueue()

        await executor.execute(ctx, eq)

        collected = _collect_events(eq)
        # Should have start_work + failed events
        assert len(collected) >= 2

    @pytest.mark.asyncio
    async def test_cancel(self) -> None:
        """Cancel creates a TaskUpdater and cancels the task."""
        registry: WorkflowRegistry = {}
        executor = BeddelA2AExecutor(registry)

        ctx = MagicMock()
        ctx.task_id = str(uuid.uuid4())
        ctx.context_id = str(uuid.uuid4())

        eq = EventQueue()
        await executor.cancel(ctx, eq)

        collected = _collect_events(eq)
        assert len(collected) >= 1
