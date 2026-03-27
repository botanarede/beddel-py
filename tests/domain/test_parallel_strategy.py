"""Unit tests for beddel.domain.strategies.parallel — ParallelExecutionStrategy."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from beddel.domain.errors import ExecutionError, PrimitiveError
from beddel.domain.models import ErrorSemantics, ExecutionContext, Step, Workflow
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
        """No config — defaults: concurrency_limit=5, fail-fast, isolate=False."""
        strategy = ParallelExecutionStrategy()
        assert strategy._parallel_config.concurrency_limit == 5

        strategy_with_config = ParallelExecutionStrategy({"concurrency_limit": 5})
        assert strategy_with_config._parallel_config.concurrency_limit == 5


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


# ---------------------------------------------------------------------------
# Story 4.2b Task 2 — Concurrency, error semantics, config validation
# ---------------------------------------------------------------------------


class TestConcurrencyLimitSemaphore:
    @pytest.mark.asyncio
    async def test_concurrency_limit_semaphore(self) -> None:
        """concurrency_limit=2, 4 parallel steps → max 2 concurrent."""
        max_concurrent = 0
        current_concurrent = 0

        async def counting_runner(step: Step, ctx: ExecutionContext) -> Any:
            nonlocal max_concurrent, current_concurrent
            current_concurrent += 1
            if current_concurrent > max_concurrent:
                max_concurrent = current_concurrent
            await asyncio.sleep(0.05)
            ctx.step_results[step.id] = f"result-{step.id}"
            current_concurrent -= 1
            return f"result-{step.id}"

        steps = [_step(f"p{i}", parallel=True) for i in range(4)]
        wf = _workflow(*steps)
        ctx = _context()
        strategy = ParallelExecutionStrategy({"concurrency_limit": 2})

        await strategy.execute(wf, ctx, counting_runner)

        assert max_concurrent == 2
        assert len(ctx.step_results) == 4


class TestConcurrencyLimitZeroUnbounded:
    @pytest.mark.asyncio
    async def test_concurrency_limit_zero_unbounded(self) -> None:
        """concurrency_limit=0 → all steps launch simultaneously."""
        max_concurrent = 0
        current_concurrent = 0

        async def counting_runner(step: Step, ctx: ExecutionContext) -> Any:
            nonlocal max_concurrent, current_concurrent
            current_concurrent += 1
            if current_concurrent > max_concurrent:
                max_concurrent = current_concurrent
            await asyncio.sleep(0.05)
            ctx.step_results[step.id] = f"result-{step.id}"
            current_concurrent -= 1
            return f"result-{step.id}"

        steps = [_step(f"p{i}", parallel=True) for i in range(4)]
        wf = _workflow(*steps)
        ctx = _context()
        strategy = ParallelExecutionStrategy({"concurrency_limit": 0})

        await strategy.execute(wf, ctx, counting_runner)

        assert max_concurrent == 4


class TestConcurrencyLimitNegativeRaises:
    def test_concurrency_limit_negative_raises(self) -> None:
        """concurrency_limit=-1 → ValueError at construction."""
        with pytest.raises(ValueError, match="concurrency_limit"):
            ParallelExecutionStrategy({"concurrency_limit": -1})


class TestFailFastCancelsSiblings:
    @pytest.mark.asyncio
    async def test_fail_fast_cancels_siblings(self) -> None:
        """One step raises, slow siblings are cancelled."""
        cancelled_steps: list[str] = []

        async def slow_runner(step: Step, ctx: ExecutionContext) -> Any:
            if step.id == "p_fail":
                raise PrimitiveError("BEDDEL-PRIM-001", "intentional failure")
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                cancelled_steps.append(step.id)
                raise
            ctx.step_results[step.id] = f"result-{step.id}"
            return f"result-{step.id}"

        p_fail = _step("p_fail", parallel=True)
        p_slow1 = _step("p_slow1", parallel=True)
        p_slow2 = _step("p_slow2", parallel=True)
        wf = _workflow(p_fail, p_slow1, p_slow2)
        ctx = _context()
        strategy = ParallelExecutionStrategy()  # default fail-fast

        with pytest.raises(ExecutionError) as exc_info:
            await strategy.execute(wf, ctx, slow_runner)

        assert exc_info.value.code == "BEDDEL-EXEC-030"
        assert exc_info.value.__cause__ is not None
        # Slow siblings should have been cancelled
        assert set(cancelled_steps) == {"p_slow1", "p_slow2"}


class TestCollectAllRunsAllSteps:
    @pytest.mark.asyncio
    async def test_collect_all_runs_all_steps(self) -> None:
        """Two fail, two succeed with collect-all → all 4 execute, BEDDEL-EXEC-031."""
        call_log: list[str] = []

        async def mixed_runner(step: Step, ctx: ExecutionContext) -> Any:
            call_log.append(step.id)
            if step.id in ("p_fail1", "p_fail2"):
                raise PrimitiveError("BEDDEL-PRIM-001", f"fail-{step.id}")
            ctx.step_results[step.id] = f"result-{step.id}"
            return f"result-{step.id}"

        p1 = _step("p_ok1", parallel=True)
        p2 = _step("p_fail1", parallel=True)
        p3 = _step("p_ok2", parallel=True)
        p4 = _step("p_fail2", parallel=True)
        wf = _workflow(p1, p2, p3, p4)
        ctx = _context()
        strategy = ParallelExecutionStrategy({"error_semantics": "collect-all"})

        with pytest.raises(ExecutionError) as exc_info:
            await strategy.execute(wf, ctx, mixed_runner)

        assert exc_info.value.code == "BEDDEL-EXEC-031"
        errors = exc_info.value.details["errors"]
        assert len(errors) == 2
        error_ids = {e["step_id"] for e in errors}
        assert error_ids == {"p_fail1", "p_fail2"}
        # All 4 steps executed
        assert set(call_log) == {"p_ok1", "p_fail1", "p_ok2", "p_fail2"}
        # Successful results stored
        assert ctx.step_results["p_ok1"] == "result-p_ok1"
        assert ctx.step_results["p_ok2"] == "result-p_ok2"


class TestCollectAllNoErrors:
    @pytest.mark.asyncio
    async def test_collect_all_no_errors(self) -> None:
        """All succeed with collect-all → no error, results in step_results."""
        p1 = _step("p1", parallel=True)
        p2 = _step("p2", parallel=True)
        wf = _workflow(p1, p2)
        ctx = _context()
        runner = _MockStepRunner()
        strategy = ParallelExecutionStrategy({"error_semantics": "collect-all"})

        await strategy.execute(wf, ctx, runner)

        assert ctx.step_results["p1"] == "result-p1"
        assert ctx.step_results["p2"] == "result-p2"


class TestInvalidErrorSemanticsRaises:
    def test_invalid_error_semantics_raises(self) -> None:
        """Invalid error_semantics → ValueError at construction."""
        with pytest.raises(ValueError):
            ParallelExecutionStrategy({"error_semantics": "invalid"})


class TestDefaultConfigValues:
    def test_default_config_values(self) -> None:
        """No config → concurrency_limit=5, FAIL_FAST, isolate_context=False."""
        strategy = ParallelExecutionStrategy()
        assert strategy._parallel_config.concurrency_limit == 5
        assert strategy._parallel_config.error_semantics == ErrorSemantics.FAIL_FAST
        assert strategy._parallel_config.isolate_context is False


class TestConfigFromDict:
    def test_config_from_dict(self) -> None:
        """Config as plain dict → parsed correctly into ParallelConfig."""
        strategy = ParallelExecutionStrategy(
            {"concurrency_limit": 3, "error_semantics": "collect-all"}
        )
        assert strategy._parallel_config.concurrency_limit == 3
        assert strategy._parallel_config.error_semantics == ErrorSemantics.COLLECT_ALL


# ---------------------------------------------------------------------------
# Story 4.2b Task 3 — Context isolation per parallel branch
# ---------------------------------------------------------------------------


class TestIsolateContextIndependentStepResults:
    @pytest.mark.asyncio
    async def test_isolate_context_independent_step_results(self) -> None:
        """isolate_context=True — branches don't see each other's results during execution."""
        seen_results: dict[str, dict[str, Any]] = {}

        async def inspecting_runner(step: Step, ctx: ExecutionContext) -> Any:
            # Record what step_results this branch can see at execution time
            seen_results[step.id] = dict(ctx.step_results)
            await asyncio.sleep(0.01)  # Ensure overlap
            ctx.step_results[step.id] = f"result-{step.id}"
            return f"result-{step.id}"

        p1 = _step("p1", parallel=True)
        p2 = _step("p2", parallel=True)
        wf = _workflow(p1, p2)
        ctx = _context()
        strategy = ParallelExecutionStrategy({"isolate_context": True})

        await strategy.execute(wf, ctx, inspecting_runner)

        # During execution, neither branch should have seen the other's result
        assert "p2" not in seen_results["p1"]
        assert "p1" not in seen_results["p2"]
        # After merge, parent has both
        assert ctx.step_results["p1"] == "result-p1"
        assert ctx.step_results["p2"] == "result-p2"


class TestIsolateContextIndependentMetadata:
    @pytest.mark.asyncio
    async def test_isolate_context_independent_metadata(self) -> None:
        """isolate_context=True — branch metadata writes don't pollute parent."""

        async def metadata_writer(step: Step, ctx: ExecutionContext) -> Any:
            ctx.metadata[f"branch_{step.id}"] = True
            ctx.step_results[step.id] = f"result-{step.id}"
            return f"result-{step.id}"

        p1 = _step("p1", parallel=True)
        p2 = _step("p2", parallel=True)
        wf = _workflow(p1, p2)
        ctx = _context()
        strategy = ParallelExecutionStrategy({"isolate_context": True})

        await strategy.execute(wf, ctx, metadata_writer)

        # Parent metadata should NOT have branch writes
        assert "branch_p1" not in ctx.metadata
        assert "branch_p2" not in ctx.metadata
        # But step_results ARE merged
        assert ctx.step_results["p1"] == "result-p1"
        assert ctx.step_results["p2"] == "result-p2"


class TestIsolateContextFalseShared:
    @pytest.mark.asyncio
    async def test_isolate_context_false_shared(self) -> None:
        """isolate_context=False — branches share context (4.2a behavior)."""

        async def metadata_writer(step: Step, ctx: ExecutionContext) -> Any:
            ctx.metadata[f"branch_{step.id}"] = True
            ctx.step_results[step.id] = f"result-{step.id}"
            return f"result-{step.id}"

        p1 = _step("p1", parallel=True)
        p2 = _step("p2", parallel=True)
        wf = _workflow(p1, p2)
        ctx = _context()
        strategy = ParallelExecutionStrategy({"isolate_context": False})

        await strategy.execute(wf, ctx, metadata_writer)

        # Shared context — metadata IS visible
        assert ctx.metadata.get("branch_p1") is True
        assert ctx.metadata.get("branch_p2") is True
        assert ctx.step_results["p1"] == "result-p1"
        assert ctx.step_results["p2"] == "result-p2"


class TestIsolateContextMergeAfterCollectAllErrors:
    @pytest.mark.asyncio
    async def test_isolate_context_merge_after_collect_all_errors(self) -> None:
        """isolate_context=True + collect-all — successful results merged despite errors."""

        async def mixed_runner(step: Step, ctx: ExecutionContext) -> Any:
            if step.id == "p_fail":
                raise PrimitiveError("BEDDEL-PRIM-001", "intentional")
            ctx.step_results[step.id] = f"result-{step.id}"
            return f"result-{step.id}"

        p_ok = _step("p_ok", parallel=True)
        p_fail = _step("p_fail", parallel=True)
        wf = _workflow(p_ok, p_fail)
        ctx = _context()
        strategy = ParallelExecutionStrategy(
            {
                "isolate_context": True,
                "error_semantics": "collect-all",
            }
        )

        with pytest.raises(ExecutionError) as exc_info:
            await strategy.execute(wf, ctx, mixed_runner)

        assert exc_info.value.code == "BEDDEL-EXEC-031"
        # Successful result should be merged to parent
        assert ctx.step_results["p_ok"] == "result-p_ok"
