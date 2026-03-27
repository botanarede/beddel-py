"""Unit tests for beddel.domain.strategies.goal_oriented — GoalOrientedStrategy."""

from __future__ import annotations

from typing import Any

import pytest

from beddel.domain.errors import ExecutionError
from beddel.domain.models import (
    DefaultDependencies,
    ExecutionContext,
    GoalConfig,
    Step,
    Workflow,
)
from beddel.domain.strategies.goal_oriented import GoalOrientedStrategy


def _step(id: str, primitive: str = "llm") -> Step:
    """Create a minimal Step for testing."""
    return Step(id=id, primitive=primitive)


def _workflow(*steps: Step) -> Workflow:
    """Create a minimal Workflow for testing."""
    return Workflow(id="wf-test", name="Test", steps=list(steps))


def _context() -> ExecutionContext:
    """Create a minimal ExecutionContext for testing."""
    return ExecutionContext(workflow_id="wf-test")


class _MockStepRunner:
    """Mock step_runner that records calls and sets configurable results."""

    def __init__(self, results: dict[str, list[Any]]) -> None:
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


class _RecordingHookManager:
    """Records on_decision calls for lifecycle hook verification."""

    def __init__(self) -> None:
        self.decisions: list[tuple[str, list[str], str]] = []

    async def on_decision(self, decision: str, alternatives: list[str], rationale: str) -> None:
        self.decisions.append((decision, alternatives, rationale))


class TestGoalMetFirstAttempt:
    @pytest.mark.asyncio
    async def test_goal_met_first_attempt(self) -> None:
        """Goal condition true on first iteration — 1 attempt, goal_met=True."""
        step = _step("check_step")
        wf = _workflow(step)
        ctx = _context()
        runner = _MockStepRunner({"check_step": ["true"]})
        strategy = GoalOrientedStrategy(
            {"goal_condition": "$stepResult.check_step", "max_attempts": 5}
        )

        await strategy.execute(wf, ctx, runner)

        meta = ctx.metadata["_goal"]
        assert meta["attempts"] == 1
        assert meta["goal_met"] is True


class TestGoalMetAfterRetries:
    @pytest.mark.asyncio
    async def test_goal_met_after_retries(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Goal condition becomes true on 3rd attempt — 3 attempts."""
        sleep_calls: list[float] = []

        async def mock_sleep(delay: float) -> None:
            sleep_calls.append(delay)

        monkeypatch.setattr("beddel.domain.strategies.goal_oriented.asyncio.sleep", mock_sleep)

        step = _step("check_step")
        wf = _workflow(step)
        ctx = _context()
        runner = _MockStepRunner({"check_step": ["false", "false", "true"]})
        strategy = GoalOrientedStrategy(
            {"goal_condition": "$stepResult.check_step", "max_attempts": 5}
        )

        await strategy.execute(wf, ctx, runner)

        meta = ctx.metadata["_goal"]
        assert meta["attempts"] == 3
        assert meta["goal_met"] is True
        assert len(sleep_calls) == 2  # backoff between attempts 1-2 and 2-3


class TestMaxAttemptsExhausted:
    @pytest.mark.asyncio
    async def test_max_attempts_exhausted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Goal never met — raises ExecutionError with BEDDEL-EXEC-040."""

        async def mock_sleep(delay: float) -> None:
            pass

        monkeypatch.setattr("beddel.domain.strategies.goal_oriented.asyncio.sleep", mock_sleep)

        step = _step("check_step")
        wf = _workflow(step)
        ctx = _context()
        runner = _MockStepRunner({"check_step": ["false"]})
        strategy = GoalOrientedStrategy(
            {"goal_condition": "$stepResult.check_step", "max_attempts": 3}
        )

        with pytest.raises(ExecutionError, match="BEDDEL-EXEC-040"):
            await strategy.execute(wf, ctx, runner)


class TestGoalConditionRequired:
    def test_goal_condition_required(self) -> None:
        """No goal_condition in config — raises ValueError."""
        with pytest.raises(ValueError, match="goal_condition is required"):
            GoalOrientedStrategy({})

    def test_goal_condition_required_none_config(self) -> None:
        """None config — raises ValueError."""
        with pytest.raises(ValueError, match="goal_condition is required"):
            GoalOrientedStrategy(None)


class TestInvalidBackoffType:
    def test_invalid_backoff_type(self) -> None:
        """Invalid backoff type — raises ValueError."""
        with pytest.raises(ValueError, match="Invalid backoff_type"):
            GoalOrientedStrategy({"goal_condition": "$stepResult.x", "backoff_type": "invalid"})


class TestFixedBackoff:
    @pytest.mark.asyncio
    async def test_fixed_backoff(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Fixed backoff returns constant backoff_base delay."""
        sleep_calls: list[float] = []

        async def mock_sleep(delay: float) -> None:
            sleep_calls.append(delay)

        monkeypatch.setattr("beddel.domain.strategies.goal_oriented.asyncio.sleep", mock_sleep)

        step = _step("s")
        wf = _workflow(step)
        ctx = _context()
        runner = _MockStepRunner({"s": ["false", "false", "true"]})
        strategy = GoalOrientedStrategy(
            {
                "goal_condition": "$stepResult.s",
                "max_attempts": 5,
                "backoff_type": "fixed",
                "backoff_base": 2.5,
            }
        )

        await strategy.execute(wf, ctx, runner)

        assert sleep_calls == [2.5, 2.5]


class TestExponentialBackoff:
    @pytest.mark.asyncio
    async def test_exponential_backoff(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Exponential backoff doubles with cap at backoff_max."""
        sleep_calls: list[float] = []

        async def mock_sleep(delay: float) -> None:
            sleep_calls.append(delay)

        monkeypatch.setattr("beddel.domain.strategies.goal_oriented.asyncio.sleep", mock_sleep)

        step = _step("s")
        wf = _workflow(step)
        ctx = _context()
        # 5 false attempts → 4 sleeps, then exhausted
        runner = _MockStepRunner({"s": ["false"]})
        strategy = GoalOrientedStrategy(
            {
                "goal_condition": "$stepResult.s",
                "max_attempts": 5,
                "backoff_type": "exponential",
                "backoff_base": 1.0,
                "backoff_max": 5.0,
            }
        )

        with pytest.raises(ExecutionError):
            await strategy.execute(wf, ctx, runner)

        # Delays: 1.0, 2.0, 4.0, 5.0 (capped)
        assert sleep_calls == [1.0, 2.0, 4.0, 5.0]


class TestAdaptiveBackoff:
    @pytest.mark.asyncio
    async def test_adaptive_backoff(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Adaptive backoff proportional to progress."""
        sleep_calls: list[float] = []

        async def mock_sleep(delay: float) -> None:
            sleep_calls.append(delay)

        monkeypatch.setattr("beddel.domain.strategies.goal_oriented.asyncio.sleep", mock_sleep)

        step = _step("s")
        wf = _workflow(step)
        ctx = _context()
        runner = _MockStepRunner({"s": ["false"]})
        strategy = GoalOrientedStrategy(
            {
                "goal_condition": "$stepResult.s",
                "max_attempts": 4,
                "backoff_type": "adaptive",
                "backoff_base": 1.0,
                "backoff_max": 10.0,
            }
        )

        with pytest.raises(ExecutionError):
            await strategy.execute(wf, ctx, runner)

        # adaptive: base * (attempt / max_attempts) * max
        # attempt 1: 1.0 * (1/4) * 10.0 = 2.5
        # attempt 2: 1.0 * (2/4) * 10.0 = 5.0
        # attempt 3: 1.0 * (3/4) * 10.0 = 7.5
        # attempt 4 is last → no sleep
        assert sleep_calls == [2.5, 5.0, 7.5]


class TestSuspendedContextExits:
    @pytest.mark.asyncio
    async def test_suspended_context_exits(self) -> None:
        """Suspended context exits early without error."""
        step = _step("s")
        wf = _workflow(step)
        ctx = _context()
        ctx.suspended = True
        runner = _MockStepRunner({"s": ["false"]})
        strategy = GoalOrientedStrategy({"goal_condition": "$stepResult.s", "max_attempts": 5})

        # Should NOT raise — exits cleanly
        await strategy.execute(wf, ctx, runner)

        meta = ctx.metadata["_goal"]
        assert meta["goal_met"] is False
        assert runner.calls == []  # no steps executed


class TestOnDecisionHookFired:
    @pytest.mark.asyncio
    async def test_on_decision_hook_fired(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """on_decision called with correct decision and rationale."""

        async def mock_sleep(delay: float) -> None:
            pass

        monkeypatch.setattr("beddel.domain.strategies.goal_oriented.asyncio.sleep", mock_sleep)

        recorder = _RecordingHookManager()
        step = _step("s")
        wf = _workflow(step)
        ctx = ExecutionContext(
            workflow_id="wf-test",
            deps=DefaultDependencies(lifecycle_hooks=recorder),  # type: ignore[arg-type]
        )
        runner = _MockStepRunner({"s": ["false", "true"]})
        strategy = GoalOrientedStrategy({"goal_condition": "$stepResult.s", "max_attempts": 5})

        await strategy.execute(wf, ctx, runner)

        assert len(recorder.decisions) == 2
        # First attempt: goal not met
        assert recorder.decisions[0][0] == "goal_retry"
        # Second attempt: goal met
        assert recorder.decisions[1][0] == "goal_achieved"
        # All calls have correct alternatives
        for _, alts, _ in recorder.decisions:
            assert alts == ["goal_achieved", "goal_retry"]
        # Rationale contains attempt info
        assert "1/5" in recorder.decisions[0][2]
        assert "2/5" in recorder.decisions[1][2]


class TestGoalConditionEvaluationFailure:
    @pytest.mark.asyncio
    async def test_goal_condition_evaluation_failure(self) -> None:
        """Resolver raises — ExecutionError with BEDDEL-EXEC-041."""
        step = _step("s")
        wf = _workflow(step)
        ctx = _context()
        runner = _MockStepRunner({"s": ["val"]})
        # Reference a non-existent step result to trigger resolver error
        strategy = GoalOrientedStrategy(
            {"goal_condition": "$stepResult.nonexistent", "max_attempts": 3}
        )

        with pytest.raises(ExecutionError, match="BEDDEL-EXEC-041"):
            await strategy.execute(wf, ctx, runner)


class TestStepsExecutedEachIteration:
    @pytest.mark.asyncio
    async def test_steps_executed_each_iteration(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """All workflow steps run on each attempt."""

        async def mock_sleep(delay: float) -> None:
            pass

        monkeypatch.setattr("beddel.domain.strategies.goal_oriented.asyncio.sleep", mock_sleep)

        s1 = _step("s1")
        s2 = _step("s2")
        wf = _workflow(s1, s2)
        ctx = _context()
        runner = _MockStepRunner({"s1": ["a"], "s2": ["false", "false", "true"]})
        strategy = GoalOrientedStrategy({"goal_condition": "$stepResult.s2", "max_attempts": 5})

        await strategy.execute(wf, ctx, runner)

        # 3 iterations × 2 steps = 6 calls
        assert len(runner.calls) == 6
        assert runner.calls == ["s1", "s2", "s1", "s2", "s1", "s2"]


class TestMetadataStored:
    @pytest.mark.asyncio
    async def test_metadata_stored(self) -> None:
        """context.metadata['_goal'] populated correctly."""
        step = _step("s")
        wf = _workflow(step)
        ctx = _context()
        runner = _MockStepRunner({"s": ["true"]})
        strategy = GoalOrientedStrategy(
            {
                "goal_condition": "$stepResult.s",
                "max_attempts": 5,
                "backoff_type": "fixed",
            }
        )

        await strategy.execute(wf, ctx, runner)

        meta = ctx.metadata["_goal"]
        assert meta["attempts"] == 1
        assert meta["goal_met"] is True
        assert meta["backoff_type"] == "fixed"


class TestDefaultConfigValues:
    def test_default_config_values(self) -> None:
        """Defaults match GoalConfig model defaults."""
        strategy = GoalOrientedStrategy({"goal_condition": "$stepResult.x"})
        defaults = GoalConfig(goal_condition="$stepResult.x")

        assert strategy._max_attempts == defaults.max_attempts
        assert strategy._backoff_type == defaults.backoff_type
        assert strategy._backoff_base == defaults.backoff_base
        assert strategy._backoff_max == defaults.backoff_max
