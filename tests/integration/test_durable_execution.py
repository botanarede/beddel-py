"""Integration tests for durable execution with checkpoint-based replay.

Tests the full lifecycle of DurableExecutionStrategy wrapping SequentialStrategy
with InMemoryEventStore, including partial replay and backward compatibility.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from beddel.adapters.event_store import InMemoryEventStore
from beddel.domain.executor import SequentialStrategy
from beddel.domain.models import ExecutionContext, Step, Workflow


def _step(step_id: str) -> Step:
    return Step(id=step_id, primitive="llm")


def _workflow(*steps: Step) -> Workflow:
    return Workflow(id="wf-test", name="Test", steps=list(steps))


def _context(workflow_id: str = "wf-test") -> ExecutionContext:
    return ExecutionContext(workflow_id=workflow_id)


def _set_result(ctx: ExecutionContext, step_id: str, value: Any) -> Any:
    ctx.step_results[step_id] = value
    return value


class TestDurableFullLifecycle:
    """Full lifecycle: execute → record events → re-execute → all replayed."""

    @pytest.mark.asyncio
    async def test_durable_full_lifecycle(self) -> None:
        """Execute 3-step workflow, verify events recorded, re-execute and verify replay."""
        from beddel.domain.strategies.durable import DurableExecutionStrategy

        store = InMemoryEventStore()
        sequential = SequentialStrategy()
        durable = DurableExecutionStrategy(wrapped=sequential, event_store=store)

        s1, s2, s3 = _step("s1"), _step("s2"), _step("s3")
        wf = _workflow(s1, s2, s3)

        # --- First execution: all steps run fresh ---
        step_runner = AsyncMock(
            side_effect=lambda step, ctx: _set_result(ctx, step.id, f"result_{step.id}")
        )
        ctx1 = _context()
        await durable.execute(wf, ctx1, step_runner)

        # All 3 steps executed
        assert step_runner.call_count == 3
        assert ctx1.step_results["s1"] == "result_s1"
        assert ctx1.step_results["s2"] == "result_s2"
        assert ctx1.step_results["s3"] == "result_s3"

        # All 3 events recorded
        events = await store.load("wf-test")
        assert len(events) == 3
        assert [e["step_id"] for e in events] == ["s1", "s2", "s3"]

        # --- Second execution: same store, all steps replayed ---
        step_runner_2 = AsyncMock()
        ctx2 = _context()
        await durable.execute(wf, ctx2, step_runner_2)

        # step_runner NOT called — all replayed
        step_runner_2.assert_not_called()

        # Results restored from events
        assert ctx2.step_results["s1"] == "result_s1"
        assert ctx2.step_results["s2"] == "result_s2"
        assert ctx2.step_results["s3"] == "result_s3"


class TestDurablePartialReplay:
    """Partial replay: steps 1-2 replayed, step 3 executes fresh."""

    @pytest.mark.asyncio
    async def test_durable_partial_replay(self) -> None:
        """Pre-record events for steps 1-2, execute — verify partial replay."""
        from beddel.domain.strategies.durable import DurableExecutionStrategy

        store = InMemoryEventStore()
        # Pre-record events for s1 and s2 only
        await store.append("wf-test", "s1", {"result": "cached_s1", "timestamp": 1000.0})
        await store.append("wf-test", "s2", {"result": "cached_s2", "timestamp": 1001.0})

        sequential = SequentialStrategy()
        durable = DurableExecutionStrategy(wrapped=sequential, event_store=store)

        s1, s2, s3 = _step("s1"), _step("s2"), _step("s3")
        wf = _workflow(s1, s2, s3)

        step_runner = AsyncMock(
            side_effect=lambda step, ctx: _set_result(ctx, step.id, f"fresh_{step.id}")
        )
        ctx = _context()
        await durable.execute(wf, ctx, step_runner)

        # Only step 3 should have called step_runner
        assert step_runner.call_count == 1
        call_step = step_runner.call_args[0][0]
        assert call_step.id == "s3"

        # Steps 1-2 restored from cache, step 3 fresh
        assert ctx.step_results["s1"] == "cached_s1"
        assert ctx.step_results["s2"] == "cached_s2"
        assert ctx.step_results["s3"] == "fresh_s3"

        # Step 3 event recorded (total events now 3)
        events = await store.load("wf-test")
        assert len(events) == 3
        assert events[2]["step_id"] == "s3"


class TestBackwardCompatibilityNoDurable:
    """Backward compatibility: plain SequentialStrategy without durable wrapper."""

    @pytest.mark.asyncio
    async def test_backward_compatibility_no_durable(self) -> None:
        """Execute workflow with plain SequentialStrategy — identical to pre-4.6a baseline."""
        sequential = SequentialStrategy()

        s1, s2, s3 = _step("s1"), _step("s2"), _step("s3")
        wf = _workflow(s1, s2, s3)

        step_runner = AsyncMock(
            side_effect=lambda step, ctx: _set_result(ctx, step.id, f"result_{step.id}")
        )
        ctx = _context()
        await sequential.execute(wf, ctx, step_runner)

        # All 3 steps executed in order
        assert step_runner.call_count == 3
        assert ctx.step_results["s1"] == "result_s1"
        assert ctx.step_results["s2"] == "result_s2"
        assert ctx.step_results["s3"] == "result_s3"

        # Call order preserved
        call_ids = [call.args[0].id for call in step_runner.call_args_list]
        assert call_ids == ["s1", "s2", "s3"]
