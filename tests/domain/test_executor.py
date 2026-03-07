"""Unit tests for beddel.domain.executor module."""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from beddel.adapters.hooks import LifecycleHookManager
from beddel.domain.errors import ExecutionError
from beddel.domain.executor import WorkflowExecutor
from beddel.domain.models import (
    BeddelEvent,
    DefaultDependencies,
    EventType,
    ExecutionContext,
    ExecutionStrategy,
    RetryConfig,
    Step,
    StrategyType,
    Workflow,
)
from beddel.domain.ports import ILifecycleHook, ILLMProvider
from beddel.domain.registry import PrimitiveRegistry

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_step(
    step_id: str = "step-1",
    primitive: str = "test-prim",
    *,
    config: dict[str, Any] | None = None,
    if_condition: str | None = None,
    then_steps: list[Step] | None = None,
    else_steps: list[Step] | None = None,
    strategy_type: StrategyType = StrategyType.FAIL,
    retry: RetryConfig | None = None,
    fallback_step: Step | None = None,
    timeout: float | None = None,
    stream: bool = False,
) -> Step:
    """Build a Step with sensible defaults for testing."""
    return Step(
        id=step_id,
        primitive=primitive,
        config=config or {},
        if_condition=if_condition,
        then_steps=then_steps,
        else_steps=else_steps,
        execution_strategy=ExecutionStrategy(
            type=strategy_type,
            retry=retry,
            fallback_step=fallback_step,
        ),
        timeout=timeout,
        stream=stream,
    )


def _make_workflow(
    steps: list[Step] | None = None,
    *,
    workflow_id: str = "wf-1",
    name: str = "Test Workflow",
) -> Workflow:
    """Build a Workflow with sensible defaults for testing."""
    return Workflow(id=workflow_id, name=name, steps=steps or [])


def _make_registry(*primitives: tuple[str, AsyncMock]) -> PrimitiveRegistry:
    """Build a PrimitiveRegistry pre-loaded with AsyncMock primitives."""
    from beddel.domain.ports import IPrimitive

    def _make_stub(mock_fn: AsyncMock) -> IPrimitive:
        class _Stub(IPrimitive):
            async def execute(self, config: dict[str, Any], context: ExecutionContext) -> Any:
                return await mock_fn(config, context)

        return _Stub()

    registry = PrimitiveRegistry()
    for prim_name, mock in primitives:
        registry.register(prim_name, _make_stub(mock))
    return registry


def _mock_primitive(return_value: Any = "ok") -> AsyncMock:
    """Create an AsyncMock that returns *return_value* when called."""
    mock = AsyncMock(return_value=return_value)
    return mock


def _registry_with_stub(
    prim_name: str = "test-prim",
    return_value: Any = "ok",
    side_effect: Any = None,
) -> tuple[PrimitiveRegistry, AsyncMock]:
    """Build a registry with a single stub primitive and return both."""
    from beddel.domain.ports import IPrimitive

    mock = AsyncMock(return_value=return_value, side_effect=side_effect)

    class _Stub(IPrimitive):
        async def execute(self, config: dict[str, Any], context: ExecutionContext) -> Any:
            return await mock(config, context)

    registry = PrimitiveRegistry()
    registry.register(prim_name, _Stub())
    return registry, mock


def _capture_registry() -> tuple[PrimitiveRegistry, list[ExecutionContext]]:
    """Return a registry whose single primitive captures its ExecutionContext."""
    captured: list[ExecutionContext] = []

    async def _capture(config: dict[str, Any], context: ExecutionContext) -> str:
        captured.append(context)
        return "ok"

    stub = AsyncMock(side_effect=_capture)
    registry = _make_registry(("test-prim", stub))
    return registry, captured


# ---------------------------------------------------------------------------
# 6.2 — Sequential execution
# ---------------------------------------------------------------------------


class TestSequentialExecution:
    """Steps execute in order and results are stored in context.step_results."""

    async def test_single_step_result_stored(self) -> None:
        registry, mock = _registry_with_stub(return_value={"answer": 42})
        wf = _make_workflow([_make_step("s1")])
        executor = WorkflowExecutor(registry)

        result = await executor.execute(wf)

        assert result["step_results"]["s1"] == {"answer": 42}

    async def test_multi_step_executes_in_order(self) -> None:
        call_order: list[str] = []

        async def _side_effect(config: dict[str, Any], ctx: ExecutionContext) -> str:
            call_order.append(config["id"])
            return config["id"]

        registry, _ = _registry_with_stub(side_effect=_side_effect)
        steps = [
            _make_step("s1", config={"id": "first"}),
            _make_step("s2", config={"id": "second"}),
            _make_step("s3", config={"id": "third"}),
        ]
        wf = _make_workflow(steps)
        executor = WorkflowExecutor(registry)

        result = await executor.execute(wf)

        assert call_order == ["first", "second", "third"]
        assert result["step_results"]["s1"] == "first"
        assert result["step_results"]["s2"] == "second"
        assert result["step_results"]["s3"] == "third"

    async def test_empty_workflow_returns_empty_results(self) -> None:
        registry = PrimitiveRegistry()
        wf = _make_workflow([])
        executor = WorkflowExecutor(registry)

        result = await executor.execute(wf)

        assert result["step_results"] == {}

    async def test_inputs_available_in_result_metadata(self) -> None:
        registry, _ = _registry_with_stub()
        wf = _make_workflow([_make_step()])
        executor = WorkflowExecutor(registry)

        result = await executor.execute(wf, inputs={"key": "val"})

        assert "metadata" in result


# ---------------------------------------------------------------------------
# 6.5 — Condition evaluation (if / then / else)
# ---------------------------------------------------------------------------


class TestConditionEvaluation:
    """Truthy condition executes step + then_steps; falsy executes else_steps."""

    async def test_truthy_condition_runs_step_and_then(self) -> None:
        then_called = False

        async def _then_effect(config: dict[str, Any], ctx: ExecutionContext) -> str:
            nonlocal then_called
            then_called = True
            return "then-result"

        registry, main_mock = _registry_with_stub(return_value="main-result")
        # Register a second primitive for the then-step
        from beddel.domain.ports import IPrimitive

        then_mock = AsyncMock(side_effect=_then_effect)

        class _ThenStub(IPrimitive):
            async def execute(self, config: dict[str, Any], context: ExecutionContext) -> Any:
                return await then_mock(config, context)

        registry.register("then-prim", _ThenStub())

        then_step = _make_step("then-s", primitive="then-prim")
        step = _make_step(
            "cond-s",
            if_condition="true",
            then_steps=[then_step],
        )
        wf = _make_workflow([step])
        executor = WorkflowExecutor(registry)

        result = await executor.execute(wf)

        assert result["step_results"]["cond-s"] == "main-result"
        assert then_called

    async def test_falsy_condition_skips_step_runs_else(self) -> None:
        else_called = False

        async def _else_effect(config: dict[str, Any], ctx: ExecutionContext) -> str:
            nonlocal else_called
            else_called = True
            return "else-result"

        registry, main_mock = _registry_with_stub(return_value="should-not-run")
        from beddel.domain.ports import IPrimitive

        else_mock = AsyncMock(side_effect=_else_effect)

        class _ElseStub(IPrimitive):
            async def execute(self, config: dict[str, Any], context: ExecutionContext) -> Any:
                return await else_mock(config, context)

        registry.register("else-prim", _ElseStub())

        else_step = _make_step("else-s", primitive="else-prim")
        step = _make_step(
            "cond-s",
            if_condition="false",
            else_steps=[else_step],
        )
        wf = _make_workflow([step])
        executor = WorkflowExecutor(registry)

        result = await executor.execute(wf)

        # Main step result should be None (condition was falsy)
        assert result["step_results"]["cond-s"] is None
        assert else_called

    async def test_falsy_condition_without_else_stores_none(self) -> None:
        registry, _ = _registry_with_stub()
        step = _make_step("cond-s", if_condition="false")
        wf = _make_workflow([step])
        executor = WorkflowExecutor(registry)

        result = await executor.execute(wf)

        assert result["step_results"]["cond-s"] is None

    async def test_truthy_condition_without_then_still_runs_step(self) -> None:
        registry, _ = _registry_with_stub(return_value="ran")
        step = _make_step("cond-s", if_condition="true")
        wf = _make_workflow([step])
        executor = WorkflowExecutor(registry)

        result = await executor.execute(wf)

        assert result["step_results"]["cond-s"] == "ran"


# ---------------------------------------------------------------------------
# 6.6 — Fail strategy
# ---------------------------------------------------------------------------


class TestFailStrategy:
    """Error re-raised as ExecutionError with BEDDEL-EXEC-002."""

    async def test_raises_execution_error(self) -> None:
        registry, _ = _registry_with_stub(side_effect=RuntimeError("boom"))
        step = _make_step("fail-s", strategy_type=StrategyType.FAIL)
        wf = _make_workflow([step])
        executor = WorkflowExecutor(registry)

        with pytest.raises(ExecutionError) as exc_info:
            await executor.execute(wf)

        assert exc_info.value.code == "BEDDEL-EXEC-002"

    async def test_error_details_contain_step_info(self) -> None:
        registry, _ = _registry_with_stub(side_effect=ValueError("bad value"))
        step = _make_step("fail-s", strategy_type=StrategyType.FAIL)
        wf = _make_workflow([step])
        executor = WorkflowExecutor(registry)

        with pytest.raises(ExecutionError) as exc_info:
            await executor.execute(wf)

        details = exc_info.value.details
        assert details["step_id"] == "fail-s"
        assert details["error_type"] == "ValueError"
        assert "bad value" in details["original_error"]

    async def test_original_error_is_chained(self) -> None:
        original = RuntimeError("root cause")
        registry, _ = _registry_with_stub(side_effect=original)
        step = _make_step("fail-s", strategy_type=StrategyType.FAIL)
        wf = _make_workflow([step])
        executor = WorkflowExecutor(registry)

        with pytest.raises(ExecutionError) as exc_info:
            await executor.execute(wf)

        assert exc_info.value.__cause__ is original


# ---------------------------------------------------------------------------
# 6.7 — Skip strategy
# ---------------------------------------------------------------------------


class TestSkipStrategy:
    """Error swallowed, execution continues."""

    async def test_skip_continues_to_next_step(self) -> None:
        call_count = 0

        async def _counting(config: dict[str, Any], ctx: ExecutionContext) -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("skip me")
            return "second-ok"

        registry, _ = _registry_with_stub(side_effect=_counting)
        steps = [
            _make_step("skip-s", strategy_type=StrategyType.SKIP),
            _make_step("next-s"),
        ]
        wf = _make_workflow(steps)
        executor = WorkflowExecutor(registry)

        result = await executor.execute(wf)

        assert result["step_results"]["skip-s"] is None
        assert result["step_results"]["next-s"] == "second-ok"

    async def test_skip_stores_none_in_step_results(self) -> None:
        registry, _ = _registry_with_stub(side_effect=RuntimeError("oops"))
        step = _make_step("skip-s", strategy_type=StrategyType.SKIP)
        wf = _make_workflow([step])
        executor = WorkflowExecutor(registry)

        result = await executor.execute(wf)

        assert result["step_results"]["skip-s"] is None


# ---------------------------------------------------------------------------
# 6.8 — Retry strategy
# ---------------------------------------------------------------------------


class TestRetryStrategy:
    """Retries up to max_attempts with backoff, raises after exhaustion."""

    @patch("beddel.domain.executor.random.uniform", return_value=1.0)
    @patch("beddel.domain.executor.asyncio.sleep", new_callable=AsyncMock)
    async def test_retry_succeeds_on_second_attempt(
        self, mock_sleep: AsyncMock, mock_uniform: MagicMock
    ) -> None:
        call_count = 0

        async def _flaky(config: dict[str, Any], ctx: ExecutionContext) -> str:
            nonlocal call_count
            call_count += 1
            if call_count <= 1:
                raise RuntimeError("transient")
            return "recovered"

        registry, _ = _registry_with_stub(side_effect=_flaky)
        retry_cfg = RetryConfig(max_attempts=3, backoff_base=2.0, jitter=True)
        step = _make_step("retry-s", strategy_type=StrategyType.RETRY, retry=retry_cfg)
        wf = _make_workflow([step])
        executor = WorkflowExecutor(registry)

        result = await executor.execute(wf)

        assert result["step_results"]["retry-s"] == "recovered"
        mock_sleep.assert_called()

    @patch("beddel.domain.executor.random.uniform", return_value=1.0)
    @patch("beddel.domain.executor.asyncio.sleep", new_callable=AsyncMock)
    async def test_retry_exhausted_raises_exec_003(
        self, mock_sleep: AsyncMock, mock_uniform: MagicMock
    ) -> None:
        registry, _ = _registry_with_stub(side_effect=RuntimeError("always fails"))
        retry_cfg = RetryConfig(max_attempts=2, backoff_base=2.0, jitter=True)
        step = _make_step("retry-s", strategy_type=StrategyType.RETRY, retry=retry_cfg)
        wf = _make_workflow([step])
        executor = WorkflowExecutor(registry)

        with pytest.raises(ExecutionError) as exc_info:
            await executor.execute(wf)

        assert exc_info.value.code == "BEDDEL-EXEC-003"
        assert exc_info.value.details["max_attempts"] == 2

    @patch("beddel.domain.executor.random.uniform", return_value=1.0)
    @patch("beddel.domain.executor.asyncio.sleep", new_callable=AsyncMock)
    async def test_retry_uses_exponential_backoff(
        self, mock_sleep: AsyncMock, mock_uniform: MagicMock
    ) -> None:
        registry, _ = _registry_with_stub(side_effect=RuntimeError("fail"))
        retry_cfg = RetryConfig(max_attempts=3, backoff_base=2.0, backoff_max=60.0, jitter=True)
        step = _make_step("retry-s", strategy_type=StrategyType.RETRY, retry=retry_cfg)
        wf = _make_workflow([step])
        executor = WorkflowExecutor(registry)

        with pytest.raises(ExecutionError):
            await executor.execute(wf)

        # Initial failure + 3 retry sleeps: backoff_base^attempt * jitter(1.0)
        # attempt 1: 2^1 * 1.0 = 2.0
        # attempt 2: 2^2 * 1.0 = 4.0
        # attempt 3: 2^3 * 1.0 = 8.0
        delays = [call.args[0] for call in mock_sleep.call_args_list]
        assert delays == [pytest.approx(2.0), pytest.approx(4.0), pytest.approx(8.0)]

    @patch("beddel.domain.executor.random.uniform", return_value=1.0)
    @patch("beddel.domain.executor.asyncio.sleep", new_callable=AsyncMock)
    async def test_retry_respects_backoff_max(
        self, mock_sleep: AsyncMock, mock_uniform: MagicMock
    ) -> None:
        registry, _ = _registry_with_stub(side_effect=RuntimeError("fail"))
        retry_cfg = RetryConfig(max_attempts=2, backoff_base=10.0, backoff_max=5.0, jitter=True)
        step = _make_step("retry-s", strategy_type=StrategyType.RETRY, retry=retry_cfg)
        wf = _make_workflow([step])
        executor = WorkflowExecutor(registry)

        with pytest.raises(ExecutionError):
            await executor.execute(wf)

        # min(10^1, 5.0) * 1.0 = 5.0 and min(10^2, 5.0) * 1.0 = 5.0
        delays = [call.args[0] for call in mock_sleep.call_args_list]
        assert all(d == pytest.approx(5.0) for d in delays)

    @patch("beddel.domain.executor.random.uniform", return_value=1.0)
    @patch("beddel.domain.executor.asyncio.sleep", new_callable=AsyncMock)
    async def test_retry_default_config_when_none(
        self, mock_sleep: AsyncMock, mock_uniform: MagicMock
    ) -> None:
        registry, _ = _registry_with_stub(side_effect=RuntimeError("fail"))
        step = _make_step("retry-s", strategy_type=StrategyType.RETRY, retry=None)
        wf = _make_workflow([step])
        executor = WorkflowExecutor(registry)

        with pytest.raises(ExecutionError) as exc_info:
            await executor.execute(wf)

        # Default RetryConfig has max_attempts=3
        assert exc_info.value.details["max_attempts"] == 3


# ---------------------------------------------------------------------------
# 6.9 — Fallback strategy
# ---------------------------------------------------------------------------


class TestFallbackStrategy:
    """Fallback step executed on error."""

    async def test_fallback_step_executes_on_error(self) -> None:
        from beddel.domain.ports import IPrimitive

        main_mock = AsyncMock(side_effect=RuntimeError("main failed"))
        fallback_mock = AsyncMock(return_value="fallback-result")

        class _MainStub(IPrimitive):
            async def execute(self, config: dict[str, Any], context: ExecutionContext) -> Any:
                return await main_mock(config, context)

        class _FallbackStub(IPrimitive):
            async def execute(self, config: dict[str, Any], context: ExecutionContext) -> Any:
                return await fallback_mock(config, context)

        registry = PrimitiveRegistry()
        registry.register("main-prim", _MainStub())
        registry.register("fb-prim", _FallbackStub())

        fb_step = _make_step("fb-s", primitive="fb-prim")
        step = _make_step(
            "main-s",
            primitive="main-prim",
            strategy_type=StrategyType.FALLBACK,
            fallback_step=fb_step,
        )
        wf = _make_workflow([step])
        executor = WorkflowExecutor(registry)

        result = await executor.execute(wf)

        assert result["step_results"]["main-s"] == "fallback-result"
        fallback_mock.assert_called_once()

    async def test_fallback_raises_exec_004_when_no_fallback_step(self) -> None:
        registry, _ = _registry_with_stub(side_effect=RuntimeError("boom"))
        step = _make_step(
            "main-s",
            strategy_type=StrategyType.FALLBACK,
            fallback_step=None,
        )
        wf = _make_workflow([step])
        executor = WorkflowExecutor(registry)

        with pytest.raises(ExecutionError) as exc_info:
            await executor.execute(wf)

        assert exc_info.value.code == "BEDDEL-EXEC-004"
        assert "no fallback step defined" in exc_info.value.message


# ---------------------------------------------------------------------------
# 6.10 — Step timeout
# ---------------------------------------------------------------------------


class TestStepTimeout:
    """asyncio.TimeoutError triggers execution strategy."""

    async def test_timeout_raises_execution_error(self) -> None:
        from beddel.domain.ports import IPrimitive

        async def _slow(config: dict[str, Any], context: ExecutionContext) -> str:
            await asyncio.sleep(10)
            return "too late"

        class _SlowStub(IPrimitive):
            async def execute(self, config: dict[str, Any], context: ExecutionContext) -> Any:
                return await _slow(config, context)

        registry = PrimitiveRegistry()
        registry.register("test-prim", _SlowStub())

        step = _make_step("timeout-s", timeout=0.01)
        wf = _make_workflow([step])
        executor = WorkflowExecutor(registry)

        with pytest.raises(ExecutionError) as exc_info:
            await executor.execute(wf)

        # The timeout produces BEDDEL-EXEC-005 internally, which is then
        # caught by _execute_step and re-wrapped by the FAIL strategy as
        # BEDDEL-EXEC-002.  The chained __cause__ carries the original 005.
        assert exc_info.value.code == "BEDDEL-EXEC-002"
        cause = exc_info.value.__cause__
        assert isinstance(cause, ExecutionError)
        assert cause.code == "BEDDEL-EXEC-005"
        assert cause.details["timeout"] == 0.01

    async def test_timeout_error_triggers_skip_strategy(self) -> None:
        from beddel.domain.ports import IPrimitive

        async def _slow(config: dict[str, Any], context: ExecutionContext) -> str:
            await asyncio.sleep(10)
            return "too late"

        class _SlowStub(IPrimitive):
            async def execute(self, config: dict[str, Any], context: ExecutionContext) -> Any:
                return await _slow(config, context)

        registry = PrimitiveRegistry()
        registry.register("test-prim", _SlowStub())

        step = _make_step("timeout-s", timeout=0.01, strategy_type=StrategyType.SKIP)
        wf = _make_workflow([step])
        executor = WorkflowExecutor(registry)

        result = await executor.execute(wf)

        assert result["step_results"]["timeout-s"] is None

    async def test_no_timeout_runs_normally(self) -> None:
        registry, _ = _registry_with_stub(return_value="fast")
        step = _make_step("fast-s", timeout=None)
        wf = _make_workflow([step])
        executor = WorkflowExecutor(registry)

        result = await executor.execute(wf)

        assert result["step_results"]["fast-s"] == "fast"


# ---------------------------------------------------------------------------
# 6.11 — Lifecycle hooks called in correct order
# ---------------------------------------------------------------------------


class TestLifecycleHookOrder:
    """on_workflow_start → on_step_start → on_step_end → on_workflow_end."""

    async def test_hook_call_order_single_step(self) -> None:
        calls: list[str] = []

        class _TrackingHook(ILifecycleHook):
            async def on_workflow_start(self, workflow_id: str, inputs: dict[str, Any]) -> None:
                calls.append("workflow_start")

            async def on_workflow_end(self, workflow_id: str, result: dict[str, Any]) -> None:
                calls.append("workflow_end")

            async def on_step_start(self, step_id: str, primitive: str) -> None:
                calls.append(f"step_start:{step_id}")

            async def on_step_end(self, step_id: str, result: Any) -> None:
                calls.append(f"step_end:{step_id}")

        registry, _ = _registry_with_stub(return_value="ok")
        hook = _TrackingHook()
        wf = _make_workflow([_make_step("s1")])
        executor = WorkflowExecutor(registry, hooks=[hook])

        await executor.execute(wf)

        assert calls == [
            "workflow_start",
            "step_start:s1",
            "step_end:s1",
            "workflow_end",
        ]

    async def test_hook_call_order_multi_step(self) -> None:
        calls: list[str] = []

        class _TrackingHook(ILifecycleHook):
            async def on_workflow_start(self, workflow_id: str, inputs: dict[str, Any]) -> None:
                calls.append("workflow_start")

            async def on_workflow_end(self, workflow_id: str, result: dict[str, Any]) -> None:
                calls.append("workflow_end")

            async def on_step_start(self, step_id: str, primitive: str) -> None:
                calls.append(f"step_start:{step_id}")

            async def on_step_end(self, step_id: str, result: Any) -> None:
                calls.append(f"step_end:{step_id}")

        registry, _ = _registry_with_stub(return_value="ok")
        hook = _TrackingHook()
        wf = _make_workflow([_make_step("s1"), _make_step("s2")])
        executor = WorkflowExecutor(registry, hooks=[hook])

        await executor.execute(wf)

        assert calls == [
            "workflow_start",
            "step_start:s1",
            "step_end:s1",
            "step_start:s2",
            "step_end:s2",
            "workflow_end",
        ]

    async def test_on_error_hook_called_on_failure(self) -> None:
        calls: list[str] = []

        class _TrackingHook(ILifecycleHook):
            async def on_error(self, step_id: str, error: Exception) -> None:
                calls.append(f"error:{step_id}")

            async def on_step_end(self, step_id: str, result: Any) -> None:
                calls.append(f"step_end:{step_id}")

        registry, _ = _registry_with_stub(side_effect=RuntimeError("oops"))
        hook = _TrackingHook()
        step = _make_step("err-s", strategy_type=StrategyType.SKIP)
        wf = _make_workflow([step])
        executor = WorkflowExecutor(registry, hooks=[hook])

        await executor.execute(wf)

        assert "error:err-s" in calls
        assert "step_end:err-s" in calls
        # on_error fires before on_step_end
        assert calls.index("error:err-s") < calls.index("step_end:err-s")

    async def test_misbehaving_hook_does_not_break_execution(self) -> None:
        class _BadHook(ILifecycleHook):
            async def on_step_start(self, step_id: str, primitive: str) -> None:
                raise RuntimeError("hook exploded")

        registry, _ = _registry_with_stub(return_value="ok")
        wf = _make_workflow([_make_step("s1")])
        executor = WorkflowExecutor(registry, hooks=[_BadHook()])

        result = await executor.execute(wf)

        assert result["step_results"]["s1"] == "ok"

    async def test_executor_dispatches_via_lifecycle_hook_manager(self) -> None:
        """Executor uses a LifecycleHookManager instance as the sole dispatch mechanism."""
        hook = AsyncMock(spec=ILifecycleHook)
        registry, _ = _registry_with_stub(return_value="ok")
        executor = WorkflowExecutor(registry, hooks=[hook])

        # The executor's internal dispatcher is a LifecycleHookManager
        assert isinstance(executor._hook_manager, LifecycleHookManager)
        # The original hook is registered inside the manager
        assert hook in executor._hook_manager._hooks


# ---------------------------------------------------------------------------
# 6.12 — execute_stream() event sequence
# ---------------------------------------------------------------------------


class TestExecuteStream:
    """Verify correct BeddelEvent sequence emitted by execute_stream()."""

    async def test_event_sequence_single_step(self) -> None:
        registry, _ = _registry_with_stub(return_value="result")
        wf = _make_workflow([_make_step("s1")])
        executor = WorkflowExecutor(registry)

        events: list[BeddelEvent] = []
        async for event in executor.execute_stream(wf):
            events.append(event)

        types = [e.event_type for e in events]
        assert types == [
            EventType.WORKFLOW_START,
            EventType.STEP_START,
            EventType.STEP_END,
            EventType.WORKFLOW_END,
        ]

    async def test_event_sequence_multi_step(self) -> None:
        registry, _ = _registry_with_stub(return_value="ok")
        wf = _make_workflow([_make_step("s1"), _make_step("s2")])
        executor = WorkflowExecutor(registry)

        events: list[BeddelEvent] = []
        async for event in executor.execute_stream(wf):
            events.append(event)

        types = [e.event_type for e in events]
        assert types == [
            EventType.WORKFLOW_START,
            EventType.STEP_START,
            EventType.STEP_END,
            EventType.STEP_START,
            EventType.STEP_END,
            EventType.WORKFLOW_END,
        ]

    async def test_stream_events_contain_correct_data(self) -> None:
        registry, _ = _registry_with_stub(return_value="hello")
        wf = _make_workflow([_make_step("s1")], workflow_id="wf-stream")
        executor = WorkflowExecutor(registry)

        events: list[BeddelEvent] = []
        async for event in executor.execute_stream(wf):
            events.append(event)

        # WORKFLOW_START carries workflow_id and inputs
        ws = events[0]
        assert ws.data["workflow_id"] == "wf-stream"

        # STEP_START carries primitive name
        ss = events[1]
        assert ss.step_id == "s1"
        assert ss.data["primitive"] == "test-prim"

        # STEP_END carries result
        se = events[2]
        assert se.step_id == "s1"
        assert se.data["result"] == "hello"

    async def test_stream_error_event_on_skip(self) -> None:
        registry, _ = _registry_with_stub(side_effect=RuntimeError("oops"))
        step = _make_step("err-s", strategy_type=StrategyType.SKIP)
        wf = _make_workflow([step])
        executor = WorkflowExecutor(registry)

        events: list[BeddelEvent] = []
        async for event in executor.execute_stream(wf):
            events.append(event)

        types = [e.event_type for e in events]
        assert EventType.ERROR in types
        error_event = next(e for e in events if e.event_type == EventType.ERROR)
        assert error_event.step_id == "err-s"
        assert "oops" in error_event.data["error"]

    @patch("beddel.domain.executor.random.uniform", return_value=1.0)
    @patch("beddel.domain.executor.asyncio.sleep", new_callable=AsyncMock)
    async def test_stream_retry_events(
        self, mock_sleep: AsyncMock, mock_uniform: MagicMock
    ) -> None:
        call_count = 0

        async def _flaky(config: dict[str, Any], ctx: ExecutionContext) -> str:
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise RuntimeError("transient")
            return "ok"

        registry, _ = _registry_with_stub(side_effect=_flaky)
        retry_cfg = RetryConfig(max_attempts=3, backoff_base=2.0, jitter=True)
        step = _make_step("retry-s", strategy_type=StrategyType.RETRY, retry=retry_cfg)
        wf = _make_workflow([step])
        executor = WorkflowExecutor(registry)

        events: list[BeddelEvent] = []
        async for event in executor.execute_stream(wf):
            events.append(event)

        types = [e.event_type for e in events]
        assert EventType.ERROR in types
        assert EventType.RETRY in types
        assert EventType.STEP_END in types

    async def test_stream_text_chunk_events(self) -> None:
        from beddel.domain.ports import IPrimitive

        async def _chunk_gen() -> Any:
            for chunk in ["Hello", " ", "World"]:
                yield chunk

        async def _stream_exec(config: dict[str, Any], context: ExecutionContext) -> Any:
            return {"stream": _chunk_gen()}

        class _StreamStub(IPrimitive):
            async def execute(self, config: dict[str, Any], context: ExecutionContext) -> Any:
                return await _stream_exec(config, context)

        registry = PrimitiveRegistry()
        registry.register("test-prim", _StreamStub())

        step = _make_step("stream-s", stream=True)
        wf = _make_workflow([step])
        executor = WorkflowExecutor(registry)

        events: list[BeddelEvent] = []
        async for event in executor.execute_stream(wf):
            events.append(event)

        text_chunks = [e for e in events if e.event_type == EventType.TEXT_CHUNK]
        assert len(text_chunks) == 3
        assert [c.data["text"] for c in text_chunks] == ["Hello", " ", "World"]

    async def test_stream_restores_hooks_after_execution(self) -> None:
        registry, _ = _registry_with_stub(return_value="ok")
        original_hook = ILifecycleHook()
        wf = _make_workflow([_make_step("s1")])
        executor = WorkflowExecutor(registry, hooks=[original_hook])

        async for _ in executor.execute_stream(wf):
            pass

        # After streaming, the collector should be removed from the manager
        assert executor._hook_manager._hooks == [original_hook]  # type: ignore[union-attr]

    async def test_stream_restores_hooks_on_error(self) -> None:
        registry, _ = _registry_with_stub(side_effect=RuntimeError("boom"))
        original_hook = ILifecycleHook()
        step = _make_step("fail-s", strategy_type=StrategyType.FAIL)
        wf = _make_workflow([step])
        executor = WorkflowExecutor(registry, hooks=[original_hook])

        with pytest.raises(ExecutionError):
            async for _ in executor.execute_stream(wf):
                pass

        assert executor._hook_manager._hooks == [original_hook]  # type: ignore[union-attr]

    async def test_execute_stream_respects_custom_strategy(self) -> None:
        """execute_stream() honours a custom IExecutionStrategy injected via execution_strategy."""
        call_order: list[str] = []

        async def _side_effect(config: dict[str, Any], ctx: ExecutionContext) -> str:
            call_order.append(config.get("id", ""))
            return config.get("id", "")

        class ReverseStrategy:
            """Iterate workflow steps in reverse declaration order."""

            async def execute(
                self,
                workflow: Workflow,
                context: ExecutionContext,
                step_runner: Any,
            ) -> None:
                """Execute steps in reverse order."""
                for step in reversed(workflow.steps):
                    await step_runner(step, context)

        registry, _ = _registry_with_stub(side_effect=_side_effect)
        steps = [
            _make_step("s1", config={"id": "first"}),
            _make_step("s2", config={"id": "second"}),
            _make_step("s3", config={"id": "third"}),
        ]
        wf = _make_workflow(steps)
        executor = WorkflowExecutor(registry)

        events: list[BeddelEvent] = []
        async for event in executor.execute_stream(wf, execution_strategy=ReverseStrategy()):
            events.append(event)

        step_start_events = [e for e in events if e.event_type == EventType.STEP_START]
        step_ids = [e.step_id for e in step_start_events]
        assert step_ids == ["s3", "s2", "s1"]


# ---------------------------------------------------------------------------
# AC-6 — Strategy injection
# ---------------------------------------------------------------------------


class TestStrategyInjection:
    """Custom IExecutionStrategy can be injected via deps and is invoked by the executor."""

    async def test_custom_strategy_is_invoked(self) -> None:
        """A ReverseStrategy iterates steps in reverse and the executor honours it."""
        call_order: list[str] = []

        async def _side_effect(config: dict[str, Any], ctx: ExecutionContext) -> str:
            call_order.append(config["id"])
            return config["id"]

        class ReverseStrategy:
            """Iterate workflow steps in reverse declaration order."""

            async def execute(
                self,
                workflow: Workflow,
                context: ExecutionContext,
                step_runner: Any,
            ) -> None:
                """Execute steps in reverse order."""
                for step in reversed(workflow.steps):
                    await step_runner(step, context)

        registry, _ = _registry_with_stub(side_effect=_side_effect)
        steps = [
            _make_step("s1", config={"id": "first"}),
            _make_step("s2", config={"id": "second"}),
            _make_step("s3", config={"id": "third"}),
        ]
        wf = _make_workflow(steps)
        executor = WorkflowExecutor(registry)

        await executor.execute(wf, execution_strategy=ReverseStrategy())

        assert call_order == ["third", "second", "first"]

    async def test_default_strategy_is_sequential(self) -> None:
        """WorkflowExecutor uses SequentialStrategy by default (declaration order)."""
        call_order: list[str] = []

        async def _side_effect(config: dict[str, Any], ctx: ExecutionContext) -> str:
            call_order.append(config["id"])
            return config["id"]

        registry, _ = _registry_with_stub(side_effect=_side_effect)
        steps = [
            _make_step("s1", config={"id": "first"}),
            _make_step("s2", config={"id": "second"}),
            _make_step("s3", config={"id": "third"}),
        ]
        wf = _make_workflow(steps)
        executor = WorkflowExecutor(registry)

        await executor.execute(wf)

        assert call_order == ["first", "second", "third"]


class TestInterruptibleContext:
    """Tests for InterruptibleContext mixin (serialize/restore/suspend)."""

    async def test_serialize_excludes_non_serializable_metadata(self) -> None:
        """Non-serializable metadata values are silently excluded."""
        ctx = ExecutionContext(workflow_id="wf-1")
        ctx.step_results = {"s1": "result1"}
        ctx.metadata = {"key1": "value1", "provider": MagicMock()}

        data = ctx.serialize()

        # Must be fully JSON-serializable
        json.dumps(data)
        assert "provider" not in data["metadata"]
        assert data["metadata"]["key1"] == "value1"
        assert data["step_results"] == {"s1": "result1"}

    async def test_restore_reconstructs_state(self) -> None:
        """restore() faithfully reconstructs all serializable fields."""
        original = ExecutionContext(workflow_id="wf-1", inputs={"topic": "AI"})
        original.step_results = {"s1": "r1", "s2": "r2"}
        original.current_step_id = "s2"
        original.suspended = True
        original.metadata = {"run_id": "abc123"}

        data = original.serialize()

        restored = ExecutionContext(workflow_id="empty")
        restored.restore(data)

        assert restored.workflow_id == original.workflow_id
        assert restored.inputs == original.inputs
        assert restored.step_results == original.step_results
        assert restored.current_step_id == original.current_step_id
        assert restored.suspended == original.suspended
        assert restored.metadata == {"run_id": "abc123"}

    async def test_suspended_stops_execution_early(self) -> None:
        """Setting suspended=True mid-run causes the executor to skip remaining steps."""
        call_count = 0

        async def _side_effect(config: dict[str, Any], ctx: ExecutionContext) -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                ctx.suspended = True
            return f"result-{call_count}"

        registry, _ = _registry_with_stub(side_effect=_side_effect)
        steps = [
            _make_step("s1"),
            _make_step("s2"),
            _make_step("s3"),
            _make_step("s4"),
        ]
        wf = _make_workflow(steps)
        executor = WorkflowExecutor(registry)

        result = await executor.execute(wf)

        assert call_count == 2
        assert len(result["step_results"]) == 2
        assert "s1" in result["step_results"]
        assert "s2" in result["step_results"]
        assert "s3" not in result["step_results"]
        assert "s4" not in result["step_results"]

    async def test_serialize_restore_round_trip(self) -> None:
        """Round-trip: populate 2-of-4 steps → suspend → serialize → restore → verify."""
        ctx = ExecutionContext(workflow_id="wf-1", inputs={"topic": "AI"})
        ctx.step_results = {"s1": "r1", "s2": "r2"}
        ctx.current_step_id = "s2"
        ctx.suspended = True
        ctx.metadata = {"run_id": "abc123"}

        checkpoint = ctx.serialize()

        # Verify checkpoint is JSON-safe
        json.dumps(checkpoint)

        new_ctx = ExecutionContext(workflow_id="empty")
        new_ctx.restore(checkpoint)

        assert new_ctx.workflow_id == "wf-1"
        assert new_ctx.inputs == {"topic": "AI"}
        assert new_ctx.step_results == {"s1": "r1", "s2": "r2"}
        assert new_ctx.current_step_id == "s2"
        assert new_ctx.suspended is True
        assert new_ctx.metadata == {"run_id": "abc123"}

    async def test_suspended_default_is_false(self) -> None:
        """A fresh ExecutionContext has suspended=False by default."""
        ctx = ExecutionContext(workflow_id="wf-1")

        assert ctx.suspended is False


# ---------------------------------------------------------------------------
# 14.3 — DELEGATE recovery strategy
# ---------------------------------------------------------------------------


class TestDelegateStrategy:
    """DELEGATE strategy asks an LLM to choose retry, skip, or fallback."""

    @patch("beddel.domain.executor.random.uniform", return_value=1.0)
    @patch("beddel.domain.executor.asyncio.sleep", new_callable=AsyncMock)
    async def test_delegate_retry_path(
        self, mock_sleep: AsyncMock, mock_uniform: MagicMock
    ) -> None:
        """LLM returns 'retry' → primitive re-executed, result stored."""
        call_count = 0

        async def _flaky(config: dict[str, Any], ctx: ExecutionContext) -> str:
            nonlocal call_count
            call_count += 1
            if call_count <= 1:
                raise RuntimeError("transient")
            return "recovered"

        registry, _ = _registry_with_stub(side_effect=_flaky)
        mock_provider = AsyncMock(spec=ILLMProvider)
        mock_provider.complete = AsyncMock(return_value={"content": "retry"})

        step = _make_step("del-s", strategy_type=StrategyType.DELEGATE)
        wf = _make_workflow([step])
        executor = WorkflowExecutor(registry, provider=mock_provider)

        result = await executor.execute(wf)

        assert result["step_results"]["del-s"] == "recovered"
        assert call_count == 2
        mock_provider.complete.assert_called_once()

    async def test_delegate_skip_path(self) -> None:
        """LLM returns 'skip' → step result is None, execution continues."""
        registry, _ = _registry_with_stub(side_effect=RuntimeError("boom"))
        mock_provider = AsyncMock(spec=ILLMProvider)
        mock_provider.complete = AsyncMock(return_value={"content": "skip"})

        step = _make_step("del-s", strategy_type=StrategyType.DELEGATE)
        wf = _make_workflow([step])
        executor = WorkflowExecutor(registry, provider=mock_provider)

        result = await executor.execute(wf)

        assert result["step_results"]["del-s"] is None
        mock_provider.complete.assert_called_once()

    async def test_delegate_fallback_path(self) -> None:
        """LLM returns 'fallback' → fallback step executes, result stored."""
        from beddel.domain.ports import IPrimitive

        main_mock = AsyncMock(side_effect=RuntimeError("main failed"))
        fallback_mock = AsyncMock(return_value="fallback-result")

        class _MainStub(IPrimitive):
            async def execute(self, config: dict[str, Any], context: ExecutionContext) -> Any:
                return await main_mock(config, context)

        class _FallbackStub(IPrimitive):
            async def execute(self, config: dict[str, Any], context: ExecutionContext) -> Any:
                return await fallback_mock(config, context)

        registry = PrimitiveRegistry()
        registry.register("main-prim", _MainStub())
        registry.register("fb-prim", _FallbackStub())

        mock_provider = AsyncMock(spec=ILLMProvider)
        mock_provider.complete = AsyncMock(return_value={"content": "fallback"})

        fb_step = _make_step("fb-s", primitive="fb-prim")
        step = _make_step(
            "del-s",
            primitive="main-prim",
            strategy_type=StrategyType.DELEGATE,
            fallback_step=fb_step,
        )
        wf = _make_workflow([step])
        executor = WorkflowExecutor(registry, provider=mock_provider)

        result = await executor.execute(wf)

        assert result["step_results"]["del-s"] == "fallback-result"
        fallback_mock.assert_called_once()

    async def test_delegate_unparseable_response(self) -> None:
        """LLM returns gibberish → BEDDEL-EXEC-011, original error chained."""
        registry, _ = _registry_with_stub(side_effect=RuntimeError("boom"))
        mock_provider = AsyncMock(spec=ILLMProvider)
        mock_provider.complete = AsyncMock(return_value={"content": "I'm not sure what to do"})

        step = _make_step("del-s", strategy_type=StrategyType.DELEGATE)
        wf = _make_workflow([step])
        executor = WorkflowExecutor(registry, provider=mock_provider)

        with pytest.raises(ExecutionError) as exc_info:
            await executor.execute(wf)

        assert exc_info.value.code == "BEDDEL-EXEC-011"
        assert isinstance(exc_info.value.__cause__, RuntimeError)

    async def test_delegate_llm_call_fails(self) -> None:
        """LLM provider raises → BEDDEL-EXEC-010."""
        registry, _ = _registry_with_stub(side_effect=RuntimeError("step fail"))
        mock_provider = AsyncMock(spec=ILLMProvider)
        mock_provider.complete = AsyncMock(side_effect=ConnectionError("LLM unreachable"))

        step = _make_step("del-s", strategy_type=StrategyType.DELEGATE)
        wf = _make_workflow([step])
        executor = WorkflowExecutor(registry, provider=mock_provider)

        with pytest.raises(ExecutionError) as exc_info:
            await executor.execute(wf)

        assert exc_info.value.code == "BEDDEL-EXEC-010"
        assert "LLM call failed" in exc_info.value.message

    async def test_delegate_no_provider_raises_error(self) -> None:
        """No llm_provider in metadata → BEDDEL-EXEC-010."""
        registry, _ = _registry_with_stub(side_effect=RuntimeError("boom"))

        step = _make_step("del-s", strategy_type=StrategyType.DELEGATE)
        wf = _make_workflow([step])
        executor = WorkflowExecutor(registry)  # no provider

        with pytest.raises(ExecutionError) as exc_info:
            await executor.execute(wf)

        assert exc_info.value.code == "BEDDEL-EXEC-010"
        assert "no LLM provider" in exc_info.value.message

    async def test_delegate_fallback_without_fallback_step(self) -> None:
        """LLM returns 'fallback' but no fallback_step → BEDDEL-EXEC-011."""
        registry, _ = _registry_with_stub(side_effect=RuntimeError("boom"))
        mock_provider = AsyncMock(spec=ILLMProvider)
        mock_provider.complete = AsyncMock(return_value={"content": "fallback"})

        step = _make_step(
            "del-s",
            strategy_type=StrategyType.DELEGATE,
            fallback_step=None,
        )
        wf = _make_workflow([step])
        executor = WorkflowExecutor(registry, provider=mock_provider)

        with pytest.raises(ExecutionError) as exc_info:
            await executor.execute(wf)

        assert exc_info.value.code == "BEDDEL-EXEC-011"
        assert "invalid action" in exc_info.value.message

    @patch("beddel.domain.executor.random.uniform", return_value=1.0)
    @patch("beddel.domain.executor.asyncio.sleep", new_callable=AsyncMock)
    async def test_delegate_step_does_not_mutate_original_step(
        self, mock_sleep: AsyncMock, mock_uniform: MagicMock
    ) -> None:
        """_delegate_step() must not mutate the original step's retry config."""
        call_count = 0

        async def _flaky(config: dict[str, Any], ctx: ExecutionContext) -> str:
            nonlocal call_count
            call_count += 1
            if call_count <= 1:
                raise RuntimeError("transient")
            return "recovered"

        registry, _ = _registry_with_stub(side_effect=_flaky)
        mock_provider = AsyncMock(spec=ILLMProvider)
        mock_provider.complete = AsyncMock(return_value={"content": "retry"})

        original_retry = RetryConfig(max_attempts=5)
        step = _make_step(
            "del-s",
            strategy_type=StrategyType.DELEGATE,
            retry=original_retry,
        )
        wf = _make_workflow([step])
        executor = WorkflowExecutor(registry, provider=mock_provider)

        await executor.execute(wf)

        # The original step's retry config must be unchanged after execution
        assert step.execution_strategy.retry is not None
        assert step.execution_strategy.retry.max_attempts == 5

    @patch("beddel.domain.executor.DefaultDependencies")
    async def test_delegate_step_uses_delegate_model_from_deps(
        self, mock_deps_cls: MagicMock
    ) -> None:
        """Custom delegate_model on DefaultDependencies is forwarded to provider.complete."""
        from beddel.domain.models import DefaultDependencies

        # Arrange — real DefaultDependencies with custom delegate_model
        mock_provider = AsyncMock(spec=ILLMProvider)
        real_deps = DefaultDependencies(
            llm_provider=mock_provider,
            delegate_model="custom-model",
        )
        mock_deps_cls.return_value = real_deps

        mock_provider.complete = AsyncMock(return_value={"content": "skip"})

        registry, _ = _registry_with_stub(side_effect=RuntimeError("boom"))
        step = _make_step("del-s", strategy_type=StrategyType.DELEGATE)
        wf = _make_workflow([step])
        executor = WorkflowExecutor(registry, provider=mock_provider)

        # Act
        await executor.execute(wf)

        # Assert — provider.complete must have been called with the custom model
        mock_provider.complete.assert_called_once()
        call_kwargs = mock_provider.complete.call_args
        assert call_kwargs.kwargs.get("model") == "custom-model"


# ---------------------------------------------------------------------------
# Story 1.11 / Task 6 — Execution Dependencies Tests
# ---------------------------------------------------------------------------


class TestExecutionDependencies:
    """Tests for DefaultDependencies and ExecutionContext.deps integration."""

    def test_default_dependencies_defaults(self) -> None:
        # Arrange / Act
        from beddel.domain.models import DefaultDependencies

        deps = DefaultDependencies()

        # Assert
        assert deps.llm_provider is None
        assert deps.lifecycle_hooks is None

    def test_default_dependencies_stores_values(self) -> None:
        # Arrange
        from beddel.domain.models import DefaultDependencies
        from beddel.domain.ports import IHookManager

        mock_provider = MagicMock(spec=ILLMProvider)
        mock_manager = MagicMock(spec=IHookManager)

        # Act
        deps = DefaultDependencies(
            llm_provider=mock_provider,
            lifecycle_hooks=mock_manager,
        )

        # Assert
        assert deps.llm_provider is mock_provider
        assert deps.lifecycle_hooks is mock_manager

    def test_execution_context_has_deps_attribute(self) -> None:
        # Arrange / Act
        from beddel.domain.models import DefaultDependencies

        context = ExecutionContext(workflow_id="test")

        # Assert
        assert isinstance(context.deps, DefaultDependencies)
        assert context.deps.llm_provider is None
        assert context.deps.lifecycle_hooks is None

    def test_default_dependencies_new_keys_default_none(self) -> None:
        """New framework-owned dependency properties default to None."""
        from beddel.domain.models import DefaultDependencies

        deps = DefaultDependencies()
        assert deps.workflow_loader is None
        assert deps.registry is None
        assert deps.tool_registry is None

    def test_default_dependencies_stores_new_keys(self) -> None:
        """New framework-owned dependency properties are stored and accessible."""
        from beddel.domain.models import DefaultDependencies, Workflow
        from beddel.domain.registry import PrimitiveRegistry

        loader = lambda name: Workflow(id=name, steps=[])  # noqa: E731
        reg = PrimitiveRegistry()
        tools: dict[str, Any] = {"my_tool": lambda: "result"}
        deps = DefaultDependencies(
            workflow_loader=loader,
            registry=reg,
            tool_registry=tools,
        )
        assert deps.workflow_loader is loader
        assert deps.registry is reg
        assert deps.tool_registry is tools


@pytest.mark.asyncio
class TestLLMPrimitiveUsesDeps:
    """Tests that LLMPrimitive reads provider from context.deps."""

    async def test_llm_primitive_uses_deps(self) -> None:
        # Arrange
        from beddel.domain.models import DefaultDependencies
        from beddel.primitives.llm import LLMPrimitive

        mock_provider = AsyncMock(spec=ILLMProvider)
        mock_provider.complete = AsyncMock(return_value={"content": "hello"})

        context = ExecutionContext(
            workflow_id="test",
            deps=DefaultDependencies(llm_provider=mock_provider),
        )
        # Deliberately do NOT set context.metadata["llm_provider"]

        primitive = LLMPrimitive()
        config = {"model": "test-model", "prompt": "hi"}

        # Act
        result = await primitive.execute(config, context)

        # Assert
        mock_provider.complete.assert_called_once()
        assert result == {"content": "hello"}


# ---------------------------------------------------------------------------
# Story 1.17 / Task 5 — LLM Provider Deps Injection Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestLLMProviderDepsInjection:
    """Tests that WorkflowExecutor injects llm_provider into context.deps."""

    async def test_provider_injected_into_deps(self) -> None:
        """Provider passed to WorkflowExecutor appears in context.deps.llm_provider."""
        provider = AsyncMock(spec=ILLMProvider)
        registry, captured = _capture_registry()

        step = _make_step("s1", primitive="test-prim")
        wf = _make_workflow([step])
        executor = WorkflowExecutor(registry, provider=provider)

        await executor.execute(wf)

        assert len(captured) == 1
        ctx = captured[0]
        assert isinstance(ctx.deps, DefaultDependencies)
        assert ctx.deps.llm_provider is provider

    async def test_no_provider_in_deps_when_none(self) -> None:
        """When no provider is given, context.deps.llm_provider is None."""
        registry, captured = _capture_registry()

        step = _make_step("s1", primitive="test-prim")
        wf = _make_workflow([step])
        executor = WorkflowExecutor(registry)  # no provider

        await executor.execute(wf)

        assert len(captured) == 1
        ctx = captured[0]
        assert isinstance(ctx.deps, DefaultDependencies)
        assert ctx.deps.llm_provider is None


@pytest.mark.asyncio
class TestLifecycleHooksDepsInjection:
    """Tests that WorkflowExecutor injects lifecycle_hooks into context.deps."""

    async def test_hooks_injected_into_deps(self) -> None:
        """Hook passed to WorkflowExecutor appears in context.deps via the manager."""
        hook = AsyncMock(spec=ILifecycleHook)
        registry, captured = _capture_registry()

        step = _make_step("s1", primitive="test-prim")
        wf = _make_workflow([step])
        executor = WorkflowExecutor(registry, hooks=[hook])

        await executor.execute(wf)

        assert len(captured) == 1
        ctx = captured[0]
        assert isinstance(ctx.deps, DefaultDependencies)
        # deps.lifecycle_hooks is the manager directly; the original hook lives inside
        manager = ctx.deps.lifecycle_hooks
        assert manager is not None
        assert hook in manager._hooks  # type: ignore[union-attr]

    async def test_empty_hooks_in_deps_when_none_provided(self) -> None:
        """When no hooks are passed, context.deps.lifecycle_hooks is the empty manager."""
        registry, captured = _capture_registry()

        step = _make_step("s1", primitive="test-prim")
        wf = _make_workflow([step])
        executor = WorkflowExecutor(registry)  # no hooks

        await executor.execute(wf)

        assert len(captured) == 1
        ctx = captured[0]
        assert isinstance(ctx.deps, DefaultDependencies)
        # deps.lifecycle_hooks is the manager wrapping zero hooks
        manager = ctx.deps.lifecycle_hooks
        assert manager is not None
        assert manager._hooks == []  # type: ignore[union-attr]


@pytest.mark.asyncio
class TestExecutorPopulatesDeps:
    """Tests that WorkflowExecutor.execute() populates context.deps."""

    async def test_executor_populates_deps(self) -> None:
        # Arrange
        mock_provider = AsyncMock(spec=ILLMProvider)
        mock_hook = AsyncMock(spec=ILifecycleHook)

        registry, captured = _capture_registry()

        step = _make_step("s1", primitive="test-prim")
        wf = _make_workflow([step])
        executor = WorkflowExecutor(registry, provider=mock_provider, hooks=[mock_hook])

        # Act
        await executor.execute(wf)

        # Assert — context was captured
        assert len(captured) == 1
        ctx = captured[0]

        # deps populated correctly
        assert isinstance(ctx.deps, DefaultDependencies)
        assert ctx.deps.llm_provider is mock_provider
        # lifecycle_hooks is the manager directly; the original hook lives inside
        manager = ctx.deps.lifecycle_hooks
        assert manager is not None
        assert mock_hook in manager._hooks  # type: ignore[union-attr]
