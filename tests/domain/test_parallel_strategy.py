"""Unit tests for beddel.domain.strategies.parallel — ParallelExecutionStrategy."""

from __future__ import annotations

from typing import Any

import pytest

from beddel.domain.errors import ExecutionError, PrimitiveError
from beddel.domain.models import ExecutionContext, Step, Workflow
from beddel.domain.strategies.parallel import ParallelExecutionStrategy


def _step(id: str, primitive: str = "llm", parallel: bool = False) -> Step:
    """Create a minimal Step for testing."""
    return Step(id=id, primitive=primitive, parallel=parallel)


def _workflow(*steps: Step) -> Workflow:
    """Create a minimal Workflow for testing."""
    return Workflow(id="wf-test", name="Test", steps=list(steps))


def _context() -> ExecutionContext:
    """Create a minimal ExecutionContext for testing."""
    return ExecutionContext(workflow_id="wf-test")


class _MockStepRunner:
    """Mock step_runner that records calls and sets configurable results."""

    def __init__(self, results: dict[str, Any] | None = None) -> None:
        self._results = results or {}
        self.calls: list[str] = []

    async def __call__(self, step: Step, context: ExecutionContext) -> Any:
        self.calls.append(step.id)
        value = self._results.get(step.id, f"result-{step.id}")
        context.step_results[step.id] = value
        return value


class _ErrorStepRunner:
    """Step runner that raises on a specific step."""

    def __init__(self, error_step_id: str) -> None:
        self._error_step_id = error_step_id
        self.calls: list[str] = []

    async def __call__(self, step: Step, context: ExecutionContext) -> Any:
        self.calls.append(step.id)
        if step.id == self._error_step_id:
            raise PrimitiveError("BEDDEL-PRIM-001", "test error")
        context.step_results[step.id] = f"result-{step.id}"
        return f"result-{step.id}"


class _SuspendingStepRunner:
    """Step runner that suspends context after first call."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def __call__(self, step: Step, context: ExecutionContext) -> Any:
        self.calls.append(step.id)
        context.step_results[step.id] = f"result-{step.id}"
        context.suspended = True
        return f"result-{step.id}"


class TestParallelAllSequential:
    @pytest.mark.asyncio
    async def test_parallel_all_sequential(self) -> None:
        """3 steps all parallel=False — calls in order, results stored."""
        s1 = _step("s1")
        s2 = _step("s2")
        s3 = _step("s3")
        wf = _workflow(s1, s2, s3)
        ctx = _context()
        runner = _MockStepRunner()
        strategy = ParallelExecutionStrategy()

        await strategy.execute(wf, ctx, runner)

        assert runner.calls == ["s1", "s2", "s3"]
        assert ctx.step_results["s1"] == "result-s1"
        assert ctx.step_results["s2"] == "result-s2"
        assert ctx.step_results["s3"] == "result-s3"


class TestParallelAllParallel:
    @pytest.mark.asyncio
    async def test_parallel_all_parallel(self) -> None:
        """3 steps all parallel=True — all called, results stored."""
        p1 = _step("p1", parallel=True)
        p2 = _step("p2", parallel=True)
        p3 = _step("p3", parallel=True)
        wf = _workflow(p1, p2, p3)
        ctx = _context()
        runner = _MockStepRunner()
        strategy = ParallelExecutionStrategy()

        await strategy.execute(wf, ctx, runner)

        assert set(runner.calls) == {"p1", "p2", "p3"}
        assert ctx.step_results["p1"] == "result-p1"
        assert ctx.step_results["p2"] == "result-p2"
        assert ctx.step_results["p3"] == "result-p3"


class TestParallelMixedGroups:
    @pytest.mark.asyncio
    async def test_parallel_mixed_groups(self) -> None:
        """[seq, par, par, seq, par, par, par, seq] = 5 groups, all called."""
        s1 = _step("s1", parallel=False)
        p1 = _step("p1", parallel=True)
        p2 = _step("p2", parallel=True)
        s2 = _step("s2", parallel=False)
        p3 = _step("p3", parallel=True)
        p4 = _step("p4", parallel=True)
        p5 = _step("p5", parallel=True)
        s3 = _step("s3", parallel=False)
        wf = _workflow(s1, p1, p2, s2, p3, p4, p5, s3)
        ctx = _context()
        runner = _MockStepRunner()
        strategy = ParallelExecutionStrategy()

        await strategy.execute(wf, ctx, runner)

        # 5 groups: (F,[s1]), (T,[p1,p2]), (F,[s2]), (T,[p3,p4,p5]), (F,[s3])
        groups = ParallelExecutionStrategy._group_steps(wf.steps)
        assert len(groups) == 5
        assert set(runner.calls) == {"s1", "p1", "p2", "s2", "p3", "p4", "p5", "s3"}


class TestParallelResultAggregation:
    @pytest.mark.asyncio
    async def test_parallel_result_aggregation(self) -> None:
        """2 parallel steps return different values, each in step_results."""
        p1 = _step("p1", parallel=True)
        p2 = _step("p2", parallel=True)
        wf = _workflow(p1, p2)
        ctx = _context()
        runner = _MockStepRunner({"p1": "alpha", "p2": "beta"})
        strategy = ParallelExecutionStrategy()

        await strategy.execute(wf, ctx, runner)

        assert ctx.step_results["p1"] == "alpha"
        assert ctx.step_results["p2"] == "beta"


class TestParallelGroupError:
    @pytest.mark.asyncio
    async def test_parallel_group_error_wraps_exception(self) -> None:
        """Parallel step raises PrimitiveError → ExecutionError BEDDEL-EXEC-030."""
        p1 = _step("p1", parallel=True)
        p2 = _step("p2", parallel=True)
        wf = _workflow(p1, p2)
        ctx = _context()
        runner = _ErrorStepRunner(error_step_id="p2")
        strategy = ParallelExecutionStrategy()

        with pytest.raises(ExecutionError) as exc_info:
            await strategy.execute(wf, ctx, runner)

        assert exc_info.value.code == "BEDDEL-EXEC-030"
        assert "p1" in exc_info.value.details["step_ids"]
        assert "p2" in exc_info.value.details["step_ids"]
        assert exc_info.value.__cause__ is not None


class TestParallelSuspended:
    @pytest.mark.asyncio
    async def test_parallel_respects_suspended_context(self) -> None:
        """Suspended after first group — not all steps called."""
        s1 = _step("s1", parallel=False)
        s2 = _step("s2", parallel=False)
        s3 = _step("s3", parallel=False)
        wf = _workflow(s1, s2, s3)
        ctx = _context()
        runner = _SuspendingStepRunner()
        strategy = ParallelExecutionStrategy()

        await strategy.execute(wf, ctx, runner)

        # s1 executes and suspends; s2 and s3 should be skipped
        assert "s1" in runner.calls
        assert len(runner.calls) == 1


class TestParallelEmptyWorkflow:
    @pytest.mark.asyncio
    async def test_parallel_empty_workflow(self) -> None:
        """No steps — no error, no calls."""
        wf = _workflow()
        ctx = _context()
        runner = _MockStepRunner()
        strategy = ParallelExecutionStrategy()

        await strategy.execute(wf, ctx, runner)

        assert runner.calls == []
        assert ctx.step_results == {}


class TestParallelSingleParallelStep:
    @pytest.mark.asyncio
    async def test_parallel_single_parallel_step(self) -> None:
        """One step with parallel=True — executes normally."""
        p1 = _step("p1", parallel=True)
        wf = _workflow(p1)
        ctx = _context()
        runner = _MockStepRunner()
        strategy = ParallelExecutionStrategy()

        await strategy.execute(wf, ctx, runner)

        assert runner.calls == ["p1"]
        assert ctx.step_results["p1"] == "result-p1"


class TestParallelDefaultConfig:
    def test_parallel_default_config(self) -> None:
        """No config — instantiation works without error."""
        strategy = ParallelExecutionStrategy()
        assert strategy._config == {}

        strategy_with_config = ParallelExecutionStrategy({"concurrency_limit": 5})
        assert strategy_with_config._config == {"concurrency_limit": 5}


class TestGroupStepsStaticMethod:
    def test_group_steps_empty(self) -> None:
        """Empty list → []."""
        assert ParallelExecutionStrategy._group_steps([]) == []

    def test_group_steps_all_sequential(self) -> None:
        """All sequential → each step in its own group."""
        s1 = _step("s1")
        s2 = _step("s2")
        groups = ParallelExecutionStrategy._group_steps([s1, s2])
        assert len(groups) == 2
        assert groups[0] == (False, [s1])
        assert groups[1] == (False, [s2])

    def test_group_steps_all_parallel(self) -> None:
        """All parallel → single group."""
        p1 = _step("p1", parallel=True)
        p2 = _step("p2", parallel=True)
        p3 = _step("p3", parallel=True)
        groups = ParallelExecutionStrategy._group_steps([p1, p2, p3])
        assert len(groups) == 1
        assert groups[0] == (True, [p1, p2, p3])

    def test_group_steps_mixed(self) -> None:
        """Mixed → [(False, [s1]), (True, [p1, p2]), (False, [s2])]."""
        s1 = _step("s1")
        p1 = _step("p1", parallel=True)
        p2 = _step("p2", parallel=True)
        s2 = _step("s2")
        groups = ParallelExecutionStrategy._group_steps([s1, p1, p2, s2])
        assert len(groups) == 3
        assert groups[0] == (False, [s1])
        assert groups[1] == (True, [p1, p2])
        assert groups[2] == (False, [s2])
