"""Integration tests for goal-oriented execution strategy with WorkflowExecutor.

Tests the full lifecycle of GoalOrientedStrategy through the executor,
including retry loops, backoff timing, max-attempts exhaustion, and
backward compatibility with SequentialStrategy.
"""

from __future__ import annotations

from typing import Any

import pytest

from beddel.domain.errors import ExecutionError
from beddel.domain.executor import WorkflowExecutor
from beddel.domain.models import ExecutionContext, Step, Workflow
from beddel.domain.ports import IPrimitive
from beddel.domain.registry import PrimitiveRegistry
from beddel.domain.strategies.goal_oriented import GoalOrientedStrategy

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _ConfigurableLLMPrimitive(IPrimitive):
    """LLM primitive that returns values from a pre-configured sequence.

    Each call pops the next value from the sequence.  When the sequence
    is exhausted, the last value is repeated.
    """

    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self._responses = list(responses)
        self._index = 0
        self.call_count = 0

    async def execute(self, config: dict[str, Any], context: ExecutionContext) -> Any:
        self.call_count += 1
        idx = min(self._index, len(self._responses) - 1)
        result = self._responses[idx]
        self._index += 1
        return result


def _make_llm_step(step_id: str = "check_step") -> Step:
    """Create an LLM step for goal-oriented testing."""
    return Step(
        id=step_id,
        primitive="llm",
        config={"model": "test/model", "prompt": "check"},
    )


def _make_workflow(steps: list[Step]) -> Workflow:
    """Create a minimal workflow with the given steps."""
    return Workflow(id="goal-test", name="Goal Test", steps=steps)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestGoalOrientedFullLifecycle:
    """Full lifecycle: false → false → true on 3rd attempt, goal met."""

    @pytest.mark.asyncio
    async def test_goal_oriented_full_lifecycle(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Execute workflow with mock LLM returning false twice then true.

        Assert goal met on 3rd attempt with correct metadata.
        """
        sleep_calls: list[float] = []

        async def mock_sleep(delay: float) -> None:
            sleep_calls.append(delay)

        monkeypatch.setattr("beddel.domain.strategies.goal_oriented.asyncio.sleep", mock_sleep)

        prim = _ConfigurableLLMPrimitive(
            [
                {"content": "false"},
                {"content": "false"},
                {"content": "true"},
            ]
        )
        registry = PrimitiveRegistry()
        registry.register("llm", prim)

        executor = WorkflowExecutor(registry)
        workflow = _make_workflow([_make_llm_step()])

        strategy = GoalOrientedStrategy(
            {
                "goal_condition": "$stepResult.check_step.content",
                "max_attempts": 5,
                "backoff_type": "fixed",
                "backoff_base": 0.01,
            }
        )

        result = await executor.execute(workflow, inputs={}, execution_strategy=strategy)

        # Goal met on 3rd attempt
        goal_meta = result["metadata"]["_goal"]
        assert goal_meta["attempts"] == 3
        assert goal_meta["goal_met"] is True
        assert goal_meta["backoff_type"] == "fixed"

        # Primitive called 3 times (once per attempt)
        assert prim.call_count == 3

        # Fixed backoff: 2 sleeps of 0.01s (between attempts 1-2 and 2-3)
        assert sleep_calls == [0.01, 0.01]

        # Step result is the last value (true)
        assert result["step_results"]["check_step"] == {"content": "true"}


class TestGoalOrientedWithExponentialBackoff:
    """Verify exponential backoff timing through the full executor."""

    @pytest.mark.asyncio
    async def test_goal_oriented_with_exponential_backoff(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Exponential backoff doubles delay with cap at backoff_max."""
        sleep_calls: list[float] = []

        async def mock_sleep(delay: float) -> None:
            sleep_calls.append(delay)

        monkeypatch.setattr("beddel.domain.strategies.goal_oriented.asyncio.sleep", mock_sleep)

        # 4 false responses → goal never met in 4 attempts, 3 sleeps
        prim = _ConfigurableLLMPrimitive(
            [
                {"content": "false"},
                {"content": "false"},
                {"content": "false"},
                {"content": "false"},
            ]
        )
        registry = PrimitiveRegistry()
        registry.register("llm", prim)

        executor = WorkflowExecutor(registry)
        workflow = _make_workflow([_make_llm_step()])

        strategy = GoalOrientedStrategy(
            {
                "goal_condition": "$stepResult.check_step.content",
                "max_attempts": 4,
                "backoff_type": "exponential",
                "backoff_base": 0.01,
                "backoff_max": 0.05,
            }
        )

        with pytest.raises(ExecutionError, match="BEDDEL-EXEC-040"):
            await executor.execute(workflow, inputs={}, execution_strategy=strategy)

        # Exponential: 0.01, 0.02, 0.04 (all under cap 0.05)
        # 3 sleeps (not on last attempt)
        assert len(sleep_calls) == 3
        assert sleep_calls[0] == pytest.approx(0.01)
        assert sleep_calls[1] == pytest.approx(0.02)
        assert sleep_calls[2] == pytest.approx(0.04)


class TestGoalOrientedMaxAttemptsIntegration:
    """Full workflow execution where goal is never met."""

    @pytest.mark.asyncio
    async def test_goal_oriented_max_attempts_integration(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Goal never met — ExecutionError raised with BEDDEL-EXEC-040."""

        async def mock_sleep(delay: float) -> None:
            pass

        monkeypatch.setattr("beddel.domain.strategies.goal_oriented.asyncio.sleep", mock_sleep)

        prim = _ConfigurableLLMPrimitive([{"content": "false"}])
        registry = PrimitiveRegistry()
        registry.register("llm", prim)

        executor = WorkflowExecutor(registry)
        workflow = _make_workflow([_make_llm_step()])

        strategy = GoalOrientedStrategy(
            {
                "goal_condition": "$stepResult.check_step.content",
                "max_attempts": 3,
                "backoff_type": "fixed",
                "backoff_base": 0.01,
            }
        )

        with pytest.raises(ExecutionError, match="BEDDEL-EXEC-040") as exc_info:
            await executor.execute(workflow, inputs={}, execution_strategy=strategy)

        assert exc_info.value.details["max_attempts"] == 3
        assert exc_info.value.details["attempts"] == 3

        # Primitive called exactly max_attempts times
        assert prim.call_count == 3


class TestBackwardCompatibilityNoGoalStrategy:
    """Full workflow execution with SequentialStrategy — identical to pre-4.5."""

    @pytest.mark.asyncio
    async def test_backward_compatibility_no_goal_strategy(self) -> None:
        """Default SequentialStrategy: steps run once, no looping, no goal metadata."""
        prim = _ConfigurableLLMPrimitive([{"content": "Hello from LLM"}])
        registry = PrimitiveRegistry()
        registry.register("llm", prim)

        executor = WorkflowExecutor(registry)
        workflow = _make_workflow(
            [
                _make_llm_step("step-1"),
                _make_llm_step("step-2"),
            ]
        )

        # No execution_strategy — defaults to SequentialStrategy
        result = await executor.execute(workflow, inputs={})

        # Both steps executed successfully
        assert result["step_results"]["step-1"] == {"content": "Hello from LLM"}
        assert result["step_results"]["step-2"] == {"content": "Hello from LLM"}

        # No goal metadata present (SequentialStrategy doesn't set it)
        assert "_goal" not in result["metadata"]

        # Standard result structure preserved
        assert "step_results" in result
        assert "metadata" in result

        # Primitive called exactly twice (once per step, no looping)
        assert prim.call_count == 2
