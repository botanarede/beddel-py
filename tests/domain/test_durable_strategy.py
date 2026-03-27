"""Unit tests for beddel.domain.strategies.durable — DurableExecutionStrategy."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from beddel.adapters.event_store import InMemoryEventStore
from beddel.domain.models import ExecutionContext, Step, Workflow
from beddel.domain.strategies.durable import DurableExecutionStrategy


def _step(step_id: str, primitive: str = "llm") -> Step:
    """Create a minimal Step for testing."""
    return Step(id=step_id, primitive=primitive)


def _workflow(*steps: Step) -> Workflow:
    """Create a minimal Workflow for testing."""
    return Workflow(id="wf-test", name="Test", steps=list(steps))


def _context(workflow_id: str = "wf-test") -> ExecutionContext:
    """Create a minimal ExecutionContext for testing."""
    return ExecutionContext(workflow_id=workflow_id)


def _set_result(ctx: ExecutionContext, step_id: str, value: Any) -> Any:
    """Helper to set step result in context (simulates step_runner side effect)."""
    ctx.step_results[step_id] = value
    return value


async def _iterate_steps(workflow: Workflow, context: ExecutionContext, step_runner: Any) -> None:
    """Mock strategy execute: calls step_runner for each step, respecting suspended."""
    for step in workflow.steps:
        if context.suspended:
            break
        await step_runner(step, context)


def _make_mock_strategy() -> MagicMock:
    """Create a mock strategy with execute as an AsyncMock using _iterate_steps."""
    strategy = MagicMock()
    strategy.execute = AsyncMock(side_effect=_iterate_steps)
    return strategy


class TestConstructorValidation:
    """Tests for DurableExecutionStrategy constructor validation."""

    def test_constructor_requires_wrapped(self) -> None:
        """None wrapped raises ValueError."""
        store = InMemoryEventStore()
        with pytest.raises(ValueError, match="wrapped"):
            DurableExecutionStrategy(wrapped=None, event_store=store)

    def test_constructor_requires_event_store(self) -> None:
        """None event_store raises ValueError."""
        mock_strategy = _make_mock_strategy()
        with pytest.raises(ValueError, match="event_store"):
            DurableExecutionStrategy(wrapped=mock_strategy, event_store=None)

    def test_constructor_stores_both(self) -> None:
        """Constructor stores wrapped and event_store."""
        mock_strategy = _make_mock_strategy()
        store = InMemoryEventStore()
        durable = DurableExecutionStrategy(wrapped=mock_strategy, event_store=store)
        assert durable._wrapped is mock_strategy
        assert durable._event_store is store


class TestFreshExecution:
    """Tests for fresh execution (no prior events)."""

    @pytest.mark.asyncio
    async def test_fresh_execution_records_events(self) -> None:
        """No prior events — all steps execute and events are recorded."""
        store = InMemoryEventStore()
        mock_strategy = _make_mock_strategy()
        step_runner = AsyncMock(
            side_effect=lambda step, ctx: _set_result(ctx, step.id, f"result_{step.id}")
        )

        s1, s2 = _step("step_1"), _step("step_2")
        wf = _workflow(s1, s2)
        ctx = _context()

        durable = DurableExecutionStrategy(wrapped=mock_strategy, event_store=store)
        await durable.execute(wf, ctx, step_runner)

        events = await store.load("wf-test")
        assert len(events) == 2
        assert events[0]["step_id"] == "step_1"
        assert events[1]["step_id"] == "step_2"

    @pytest.mark.asyncio
    async def test_step_runner_called_for_new_steps(self) -> None:
        """Original step_runner is called for non-replayed steps."""
        store = InMemoryEventStore()
        mock_strategy = _make_mock_strategy()
        step_runner = AsyncMock(side_effect=lambda step, ctx: _set_result(ctx, step.id, "ok"))

        wf = _workflow(_step("step_1"))
        ctx = _context()

        durable = DurableExecutionStrategy(wrapped=mock_strategy, event_store=store)
        await durable.execute(wf, ctx, step_runner)

        step_runner.assert_called_once()

    @pytest.mark.asyncio
    async def test_event_contains_timestamp(self) -> None:
        """Appended events have a timestamp field."""
        store = InMemoryEventStore()
        mock_strategy = _make_mock_strategy()
        step_runner = AsyncMock(side_effect=lambda step, ctx: _set_result(ctx, step.id, "ok"))

        wf = _workflow(_step("step_1"))
        ctx = _context()

        durable = DurableExecutionStrategy(wrapped=mock_strategy, event_store=store)
        await durable.execute(wf, ctx, step_runner)

        events = await store.load("wf-test")
        assert len(events) == 1
        assert "timestamp" in events[0]
        assert isinstance(events[0]["timestamp"], float)


class TestReplay:
    """Tests for checkpoint-based replay."""

    @pytest.mark.asyncio
    async def test_replay_skips_completed_steps(self) -> None:
        """Pre-load events for step_1 — step_1 is skipped, step_2 executes."""
        store = InMemoryEventStore()
        await store.append("wf-test", "step_1", {"result": "cached_1", "timestamp": 1000.0})

        mock_strategy = _make_mock_strategy()
        step_runner = AsyncMock(
            side_effect=lambda step, ctx: _set_result(ctx, step.id, f"fresh_{step.id}")
        )

        wf = _workflow(_step("step_1"), _step("step_2"))
        ctx = _context()

        durable = DurableExecutionStrategy(wrapped=mock_strategy, event_store=store)
        await durable.execute(wf, ctx, step_runner)

        # step_runner should only be called for step_2
        assert step_runner.call_count == 1
        call_step = step_runner.call_args[0][0]
        assert call_step.id == "step_2"

    @pytest.mark.asyncio
    async def test_replay_restores_results(self) -> None:
        """context.step_results populated from stored event for replayed steps."""
        store = InMemoryEventStore()
        await store.append("wf-test", "step_1", {"result": "stored_result", "timestamp": 1000.0})

        mock_strategy = _make_mock_strategy()
        step_runner = AsyncMock(
            side_effect=lambda step, ctx: _set_result(ctx, step.id, f"fresh_{step.id}")
        )

        wf = _workflow(_step("step_1"), _step("step_2"))
        ctx = _context()

        durable = DurableExecutionStrategy(wrapped=mock_strategy, event_store=store)
        await durable.execute(wf, ctx, step_runner)

        assert ctx.step_results["step_1"] == "stored_result"
        assert ctx.step_results["step_2"] == "fresh_step_2"

    @pytest.mark.asyncio
    async def test_step_runner_not_called_for_replayed_steps(self) -> None:
        """Original step_runner is NOT called for replayed steps."""
        store = InMemoryEventStore()
        await store.append("wf-test", "step_1", {"result": "cached", "timestamp": 1000.0})

        mock_strategy = _make_mock_strategy()
        step_runner = AsyncMock(side_effect=lambda step, ctx: _set_result(ctx, step.id, "fresh"))

        wf = _workflow(_step("step_1"))
        ctx = _context()

        durable = DurableExecutionStrategy(wrapped=mock_strategy, event_store=store)
        await durable.execute(wf, ctx, step_runner)

        step_runner.assert_not_called()


class TestWrapsAnyStrategy:
    """Tests for decorator pattern — wraps any strategy."""

    @pytest.mark.asyncio
    async def test_wraps_mock_strategy(self) -> None:
        """Works with a mock strategy."""
        store = InMemoryEventStore()
        mock_strategy = _make_mock_strategy()
        step_runner = AsyncMock(side_effect=lambda step, ctx: _set_result(ctx, step.id, "ok"))

        wf = _workflow(_step("step_1"))
        ctx = _context()

        durable = DurableExecutionStrategy(wrapped=mock_strategy, event_store=store)
        await durable.execute(wf, ctx, step_runner)

        mock_strategy.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_wraps_sequential_strategy(self) -> None:
        """Works with SequentialStrategy."""
        from beddel.domain.executor import SequentialStrategy

        store = InMemoryEventStore()
        sequential = SequentialStrategy()
        step_runner = AsyncMock(
            side_effect=lambda step, ctx: _set_result(ctx, step.id, f"result_{step.id}")
        )

        wf = _workflow(_step("step_1"), _step("step_2"))
        ctx = _context()

        durable = DurableExecutionStrategy(wrapped=sequential, event_store=store)
        await durable.execute(wf, ctx, step_runner)

        assert ctx.step_results["step_1"] == "result_step_1"
        assert ctx.step_results["step_2"] == "result_step_2"
        events = await store.load("wf-test")
        assert len(events) == 2


class TestSuspendedContext:
    """Tests for suspended context handling."""

    @pytest.mark.asyncio
    async def test_suspended_context_respected(self) -> None:
        """Wrapped strategy's suspension handling is preserved."""
        store = InMemoryEventStore()
        mock_strategy = _make_mock_strategy()

        call_count = 0

        async def suspending_runner(step: Step, ctx: ExecutionContext) -> Any:
            nonlocal call_count
            call_count += 1
            ctx.step_results[step.id] = f"val_{call_count}"
            if step.id == "step_1":
                ctx.suspended = True
            return f"val_{call_count}"

        wf = _workflow(_step("step_1"), _step("step_2"))
        ctx = _context()

        durable = DurableExecutionStrategy(wrapped=mock_strategy, event_store=store)
        await durable.execute(wf, ctx, suspending_runner)

        # step_2 should not have executed because context was suspended
        assert "step_1" in ctx.step_results
        assert "step_2" not in ctx.step_results
