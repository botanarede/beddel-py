"""Unit tests for beddel.domain.strategies.reflection — ReflectionStrategy."""

from __future__ import annotations

from typing import Any

import pytest

from beddel.domain.errors import ExecutionError
from beddel.domain.models import ExecutionContext, Step, Workflow
from beddel.domain.strategies.reflection import ReflectionStrategy


def _step(id: str, primitive: str = "llm", tags: list[str] | None = None) -> Step:
    """Create a minimal Step for testing."""
    return Step(id=id, primitive=primitive, tags=tags or [])


def _workflow(*steps: Step) -> Workflow:
    """Create a minimal Workflow for testing."""
    return Workflow(id="wf-test", name="Test", steps=list(steps))


def _context() -> ExecutionContext:
    """Create a minimal ExecutionContext for testing."""
    return ExecutionContext(workflow_id="wf-test")


class _MockStepRunner:
    """Mock step_runner that records calls and sets configurable results."""

    def __init__(self, results: dict[str, list[Any]]) -> None:
        """Initialise with per-step-id result sequences.

        Args:
            results: Mapping of step id to a list of return values.
                Each call pops the first value; if exhausted, reuses last.
        """
        self._results = results
        self._counters: dict[str, int] = {}
        self.calls: list[str] = []

    async def __call__(self, step: Step, context: ExecutionContext) -> Any:
        self.calls.append(step.id)
        sid = step.id
        idx = self._counters.get(sid, 0)
        values = self._results.get(sid, [None])
        value = values[min(idx, len(values) - 1)]
        self._counters[sid] = idx + 1
        context.step_results[sid] = value
        return value


class TestReflectionConvergence:
    @pytest.mark.asyncio
    async def test_reflection_converges_exact_match(self) -> None:
        """Exact-match converges when two consecutive evals are equal."""
        gen1 = _step("gen1", tags=["generate"])
        gen2 = _step("gen2", tags=["generate"])
        eval1 = _step("eval1", tags=["evaluate"])
        wf = _workflow(gen1, gen2, eval1)
        ctx = _context()
        runner = _MockStepRunner({"gen1": ["a"], "gen2": ["b"], "eval1": ["good"]})
        strategy = ReflectionStrategy({"max_iterations": 5})

        await strategy.execute(wf, ctx, runner)

        meta = ctx.metadata["_reflection"]
        assert meta["converged"] is True
        assert meta["iterations"] == 2
        assert meta["algorithm"] == "exact-match"

    @pytest.mark.asyncio
    async def test_reflection_max_iterations_reached(self) -> None:
        """Loop exits after max_iterations when eval never repeats."""
        gen = _step("gen", tags=["generate"])
        ev = _step("ev", tags=["evaluate"])
        wf = _workflow(gen, ev)
        ctx = _context()
        runner = _MockStepRunner({"gen": ["x"], "ev": ["result_1", "result_2", "result_3"]})
        strategy = ReflectionStrategy({"max_iterations": 3})

        await strategy.execute(wf, ctx, runner)

        meta = ctx.metadata["_reflection"]
        assert meta["converged"] is False
        assert meta["iterations"] == 3

    @pytest.mark.asyncio
    async def test_reflection_single_iteration_convergence(self) -> None:
        """First iteration never converges (previous=None); second does."""
        gen = _step("gen", tags=["generate"])
        ev = _step("ev", tags=["evaluate"])
        wf = _workflow(gen, ev)
        ctx = _context()
        runner = _MockStepRunner({"gen": ["x"], "ev": ["same"]})
        strategy = ReflectionStrategy({"max_iterations": 10})

        await strategy.execute(wf, ctx, runner)

        meta = ctx.metadata["_reflection"]
        assert meta["converged"] is True
        assert meta["iterations"] == 2


class TestReflectionErrors:
    @pytest.mark.asyncio
    async def test_reflection_no_generate_steps_raises(self) -> None:
        """Raises ExecutionError when no generate-tagged steps exist."""
        ev = _step("ev", tags=["evaluate"])
        wf = _workflow(ev)
        ctx = _context()
        runner = _MockStepRunner({})
        strategy = ReflectionStrategy()

        with pytest.raises(ExecutionError, match="BEDDEL-EXEC-020"):
            await strategy.execute(wf, ctx, runner)

    @pytest.mark.asyncio
    async def test_reflection_no_evaluate_steps_raises(self) -> None:
        """Raises ExecutionError when no evaluate-tagged steps exist."""
        gen = _step("gen", tags=["generate"])
        wf = _workflow(gen)
        ctx = _context()
        runner = _MockStepRunner({})
        strategy = ReflectionStrategy()

        with pytest.raises(ExecutionError, match="BEDDEL-EXEC-021"):
            await strategy.execute(wf, ctx, runner)


class TestReflectionFeedback:
    @pytest.mark.asyncio
    async def test_reflection_feedback_injected(self) -> None:
        """After a non-converging iteration, feedback is injected."""
        gen = _step("gen", tags=["generate"])
        ev = _step("ev", tags=["evaluate"])
        wf = _workflow(gen, ev)
        ctx = _context()
        runner = _MockStepRunner({"gen": ["x"], "ev": ["feedback_val", "feedback_val"]})
        strategy = ReflectionStrategy({"max_iterations": 5})

        await strategy.execute(wf, ctx, runner)

        # After iteration 1 (no convergence), feedback should be set
        # Iteration 2 converges, so feedback from iter 1 should be present
        assert ctx.step_results["_reflection_feedback"] == "feedback_val"


class TestReflectionThreshold:
    @pytest.mark.asyncio
    async def test_reflection_threshold_convergence(self) -> None:
        """Threshold algorithm converges when eval >= threshold."""
        gen = _step("gen", tags=["generate"])
        ev = _step("ev", tags=["evaluate"])
        wf = _workflow(gen, ev)
        ctx = _context()
        runner = _MockStepRunner({"gen": ["x"], "ev": [0.5, 0.85]})
        strategy = ReflectionStrategy(
            {
                "convergence_algorithm": "threshold",
                "convergence_threshold": 0.8,
                "max_iterations": 5,
            }
        )

        await strategy.execute(wf, ctx, runner)

        meta = ctx.metadata["_reflection"]
        assert meta["converged"] is True
        assert meta["iterations"] == 2
        assert meta["algorithm"] == "threshold"

    @pytest.mark.asyncio
    async def test_reflection_threshold_below_threshold(self) -> None:
        """Threshold algorithm does not converge when eval < threshold."""
        gen = _step("gen", tags=["generate"])
        ev = _step("ev", tags=["evaluate"])
        wf = _workflow(gen, ev)
        ctx = _context()
        runner = _MockStepRunner({"gen": ["x"], "ev": [0.5]})
        strategy = ReflectionStrategy(
            {
                "convergence_algorithm": "threshold",
                "convergence_threshold": 0.8,
                "max_iterations": 3,
            }
        )

        await strategy.execute(wf, ctx, runner)

        meta = ctx.metadata["_reflection"]
        assert meta["converged"] is False
        assert meta["iterations"] == 3


class TestReflectionSuspended:
    @pytest.mark.asyncio
    async def test_reflection_respects_suspended_context(self) -> None:
        """Loop exits early when context.suspended is set."""
        gen = _step("gen", tags=["generate"])
        ev = _step("ev", tags=["evaluate"])
        wf = _workflow(gen, ev)
        ctx = _context()

        call_count = 0

        async def suspending_runner(step: Step, context: ExecutionContext) -> Any:
            nonlocal call_count
            call_count += 1
            context.step_results[step.id] = f"val_{call_count}"
            # Suspend after first generate step completes
            if step.id == "gen":
                context.suspended = True
            return f"val_{call_count}"

        strategy = ReflectionStrategy({"max_iterations": 5})

        await strategy.execute(wf, ctx, suspending_runner)

        meta = ctx.metadata["_reflection"]
        assert meta["iterations"] < 5


class TestReflectionDefaults:
    def test_reflection_default_config(self) -> None:
        """Default config values are applied when no config is given."""
        strategy = ReflectionStrategy()
        assert strategy._max_iterations == 5
        assert strategy._algorithm == "exact-match"
        assert strategy._threshold == 0.9
