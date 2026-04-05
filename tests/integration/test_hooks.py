"""Integration tests for executor hook wiring (Story 3.2, Task 5).

Verifies that the :class:`~beddel.domain.executor.WorkflowExecutor` correctly
dispatches lifecycle hooks during workflow execution — covering event order,
argument correctness, error/retry hooks, misbehaving hook isolation, streaming,
dependency injection, and the no-hooks path.
"""

from __future__ import annotations

import unittest.mock
from typing import Any

from beddel.adapters.hooks import LifecycleHookManager
from beddel.domain.executor import WorkflowExecutor
from beddel.domain.models import (
    DefaultDependencies,
    EventType,
    ExecutionContext,
    ExecutionStrategy,
    RetryConfig,
    Step,
    StrategyType,
    Workflow,
)
from beddel.domain.ports import ILifecycleHook, IPrimitive
from beddel.domain.registry import PrimitiveRegistry

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


class _RecordingHook(ILifecycleHook):
    """Async hook that records all calls as (method_name, args) tuples."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    async def on_workflow_start(self, workflow_id: str, inputs: dict[str, Any]) -> None:
        self.calls.append(("on_workflow_start", (workflow_id, inputs)))

    async def on_workflow_end(self, workflow_id: str, result: dict[str, Any]) -> None:
        self.calls.append(("on_workflow_end", (workflow_id, result)))

    async def on_step_start(self, step_id: str, primitive: str) -> None:
        self.calls.append(("on_step_start", (step_id, primitive)))

    async def on_step_end(self, step_id: str, result: Any) -> None:
        self.calls.append(("on_step_end", (step_id, result)))

    async def on_error(self, step_id: str, error: Exception) -> None:
        self.calls.append(("on_error", (step_id, error)))

    async def on_retry(self, step_id: str, attempt: int, error: Exception) -> None:
        self.calls.append(("on_retry", (step_id, attempt, error)))


class _MisbehavingHook(ILifecycleHook):
    """Async hook that raises RuntimeError on every method."""

    async def on_workflow_start(self, workflow_id: str, inputs: dict[str, Any]) -> None:
        raise RuntimeError("boom")

    async def on_workflow_end(self, workflow_id: str, result: dict[str, Any]) -> None:
        raise RuntimeError("boom")

    async def on_step_start(self, step_id: str, primitive: str) -> None:
        raise RuntimeError("boom")

    async def on_step_end(self, step_id: str, result: Any) -> None:
        raise RuntimeError("boom")

    async def on_error(self, step_id: str, error: Exception) -> None:
        raise RuntimeError("boom")

    async def on_retry(self, step_id: str, attempt: int, error: Exception) -> None:
        raise RuntimeError("boom")


class _StepDispatchPrimitive(IPrimitive):
    """Mock primitive returning pre-configured results keyed by step id."""

    def __init__(self, results: dict[str, Any], *, default: Any = None) -> None:
        self._results = results
        self._default = default

    async def execute(self, config: dict[str, Any], context: ExecutionContext) -> Any:
        """Return the pre-configured result for the current step."""
        return self._results.get(context.current_step_id, self._default)


class _FailingPrimitive(IPrimitive):
    """Mock primitive that always raises RuntimeError."""

    async def execute(self, config: dict[str, Any], context: ExecutionContext) -> Any:
        """Raise an error to exercise the error-hook path."""
        msg = "step failed"
        raise RuntimeError(msg)


class _FailNTimesPrimitive(IPrimitive):
    """Mock primitive that fails N times then succeeds.

    Args:
        fail_count: Number of times to raise before returning success.
        success_value: Value returned after exhausting failures.
    """

    def __init__(self, fail_count: int, success_value: Any = "recovered") -> None:
        self._fail_count = fail_count
        self._success_value = success_value
        self._call_count = 0

    async def execute(self, config: dict[str, Any], context: ExecutionContext) -> Any:
        """Fail for the first N calls, then succeed."""
        self._call_count += 1
        if self._call_count <= self._fail_count:
            msg = f"transient failure #{self._call_count}"
            raise RuntimeError(msg)
        return self._success_value


class _ContextCapturePrimitive(IPrimitive):
    """Mock primitive that captures context.deps.lifecycle_hooks during execution."""

    def __init__(self) -> None:
        self.captured_hooks: Any = None

    async def execute(self, config: dict[str, Any], context: ExecutionContext) -> Any:
        """Capture the lifecycle_hooks from context.deps."""
        self.captured_hooks = context.deps.lifecycle_hooks
        return "captured"


def _build_executor(
    step_results: dict[str, Any],
    *,
    hooks: list[ILifecycleHook] | None = None,
    failing_primitives: set[str] | None = None,
) -> WorkflowExecutor:
    """Build a WorkflowExecutor with mock primitives and optional hooks."""
    registry = PrimitiveRegistry()
    registry.register("llm", _StepDispatchPrimitive(step_results))
    if failing_primitives:
        for name in failing_primitives:
            registry.register(name, _FailingPrimitive())
    hook_manager = LifecycleHookManager(hooks) if hooks is not None else None
    deps = DefaultDependencies(lifecycle_hooks=hook_manager) if hook_manager is not None else None
    return WorkflowExecutor(registry, deps=deps)


def _simple_workflow(
    *,
    workflow_id: str = "test-wf",
    step_id: str = "step-1",
    primitive: str = "llm",
    strategy_type: StrategyType = StrategyType.FAIL,
    retry_config: RetryConfig | None = None,
) -> Workflow:
    """Build a single-step workflow for testing."""
    strategy = ExecutionStrategy(type=strategy_type, retry=retry_config)
    return Workflow(
        id=workflow_id,
        name="Test Workflow",
        steps=[
            Step(
                id=step_id,
                primitive=primitive,
                config={"prompt": "Hello"},
                execution_strategy=strategy,
            ),
        ],
    )


def _multi_step_workflow() -> Workflow:
    """Build a two-step workflow for ordering verification."""
    return Workflow(
        id="multi-wf",
        name="Multi-Step Workflow",
        steps=[
            Step(id="s1", primitive="llm", config={"prompt": "first"}),
            Step(id="s2", primitive="llm", config={"prompt": "second"}),
        ],
    )


# ---------------------------------------------------------------------------
# 5.2 — Hook event order
# ---------------------------------------------------------------------------


class TestHookEventOrder:
    """Verify on_workflow_start, on_step_start, on_step_end, on_workflow_end order."""

    async def test_single_step_hook_order(self) -> None:
        """Single-step workflow fires hooks in correct lifecycle order."""
        hook = _RecordingHook()
        executor = _build_executor({"step-1": "ok"}, hooks=[hook])
        workflow = _simple_workflow()

        await executor.execute(workflow, inputs={})

        method_names = [name for name, _ in hook.calls]
        assert method_names == [
            "on_workflow_start",
            "on_step_start",
            "on_step_end",
            "on_workflow_end",
        ]

    async def test_multi_step_hook_order(self) -> None:
        """Two-step workflow fires step hooks in declaration order."""
        hook = _RecordingHook()
        executor = _build_executor({"s1": "r1", "s2": "r2"}, hooks=[hook])
        workflow = _multi_step_workflow()

        await executor.execute(workflow, inputs={})

        method_names = [name for name, _ in hook.calls]
        assert method_names == [
            "on_workflow_start",
            "on_step_start",
            "on_step_end",
            "on_step_start",
            "on_step_end",
            "on_workflow_end",
        ]


# ---------------------------------------------------------------------------
# 5.3 — Hook receives correct arguments
# ---------------------------------------------------------------------------


class TestHookArguments:
    """Verify correct args passed to each hook method."""

    async def test_workflow_start_receives_id_and_inputs(self) -> None:
        """on_workflow_start receives workflow_id and inputs dict."""
        hook = _RecordingHook()
        executor = _build_executor({"step-1": "ok"}, hooks=[hook])
        workflow = _simple_workflow(workflow_id="wf-42")

        await executor.execute(workflow, inputs={"topic": "AI"})

        wf_start = [c for c in hook.calls if c[0] == "on_workflow_start"]
        assert len(wf_start) == 1
        assert wf_start[0][1] == ("wf-42", {"topic": "AI"})

    async def test_step_start_receives_step_id_and_primitive(self) -> None:
        """on_step_start receives step_id and primitive name."""
        hook = _RecordingHook()
        executor = _build_executor({"step-1": "ok"}, hooks=[hook])
        workflow = _simple_workflow(step_id="step-1", primitive="llm")

        await executor.execute(workflow, inputs={})

        step_start = [c for c in hook.calls if c[0] == "on_step_start"]
        assert len(step_start) == 1
        assert step_start[0][1] == ("step-1", "llm")

    async def test_step_end_receives_step_id_and_result(self) -> None:
        """on_step_end receives step_id and the primitive's return value."""
        hook = _RecordingHook()
        executor = _build_executor({"step-1": {"answer": 42}}, hooks=[hook])
        workflow = _simple_workflow()

        await executor.execute(workflow, inputs={})

        step_end = [c for c in hook.calls if c[0] == "on_step_end"]
        assert len(step_end) == 1
        assert step_end[0][1] == ("step-1", {"answer": 42})

    async def test_workflow_end_receives_id_and_result(self) -> None:
        """on_workflow_end receives workflow_id and the full result dict."""
        hook = _RecordingHook()
        executor = _build_executor({"step-1": "ok"}, hooks=[hook])
        workflow = _simple_workflow(workflow_id="wf-99")

        await executor.execute(workflow, inputs={})

        wf_end = [c for c in hook.calls if c[0] == "on_workflow_end"]
        assert len(wf_end) == 1
        wf_id, result = wf_end[0][1]
        assert wf_id == "wf-99"
        assert result["step_results"]["step-1"] == "ok"


# ---------------------------------------------------------------------------
# 5.4 — Error hook
# ---------------------------------------------------------------------------


class TestErrorHook:
    """Verify on_error is called when a step fails."""

    async def test_on_error_called_on_step_failure(self) -> None:
        """on_error fires with step_id and exception when step raises (SKIP strategy)."""
        hook = _RecordingHook()
        registry = PrimitiveRegistry()
        registry.register("llm", _FailingPrimitive())
        executor = WorkflowExecutor(
            registry, deps=DefaultDependencies(lifecycle_hooks=LifecycleHookManager([hook]))
        )
        workflow = _simple_workflow(strategy_type=StrategyType.SKIP)

        await executor.execute(workflow, inputs={})

        error_calls = [c for c in hook.calls if c[0] == "on_error"]
        assert len(error_calls) == 1
        step_id, error = error_calls[0][1]
        assert step_id == "step-1"
        assert isinstance(error, RuntimeError)
        assert "step failed" in str(error)

    async def test_on_error_not_called_on_success(self) -> None:
        """on_error is NOT called when all steps succeed."""
        hook = _RecordingHook()
        executor = _build_executor({"step-1": "ok"}, hooks=[hook])
        workflow = _simple_workflow()

        await executor.execute(workflow, inputs={})

        error_calls = [c for c in hook.calls if c[0] == "on_error"]
        assert len(error_calls) == 0


# ---------------------------------------------------------------------------
# 5.5 — Retry hook
# ---------------------------------------------------------------------------


class TestRetryHook:
    """Verify on_retry is called with attempt number when step retries."""

    async def test_on_retry_called_with_attempt_number(self) -> None:
        """on_retry fires with step_id, attempt number, and error on each retry."""
        hook = _RecordingHook()
        # Fails once, succeeds on second call (first retry attempt)
        prim = _FailNTimesPrimitive(fail_count=1, success_value="recovered")
        registry = PrimitiveRegistry()
        registry.register("llm", prim)
        executor = WorkflowExecutor(
            registry, deps=DefaultDependencies(lifecycle_hooks=LifecycleHookManager([hook]))
        )
        retry_cfg = RetryConfig(
            max_attempts=2,
            backoff_base=0.0,
            backoff_max=0.0,
            jitter=False,
        )
        workflow = _simple_workflow(
            strategy_type=StrategyType.RETRY,
            retry_config=retry_cfg,
        )

        with unittest.mock.patch(
            "beddel.domain.executor.asyncio.sleep",
            new_callable=unittest.mock.AsyncMock,
        ):
            result = await executor.execute(workflow, inputs={})

        # Workflow recovered
        assert result["step_results"]["step-1"] == "recovered"

        retry_calls = [c for c in hook.calls if c[0] == "on_retry"]
        assert len(retry_calls) >= 1
        # First retry attempt is attempt=1
        step_id, attempt, error = retry_calls[0][1]
        assert step_id == "step-1"
        assert attempt == 1
        assert isinstance(error, RuntimeError)

    async def test_on_retry_not_called_on_success(self) -> None:
        """on_retry is NOT called when step succeeds on first attempt."""
        hook = _RecordingHook()
        executor = _build_executor({"step-1": "ok"}, hooks=[hook])
        workflow = _simple_workflow()

        await executor.execute(workflow, inputs={})

        retry_calls = [c for c in hook.calls if c[0] == "on_retry"]
        assert len(retry_calls) == 0


# ---------------------------------------------------------------------------
# 5.6 — Misbehaving hook does not break workflow
# ---------------------------------------------------------------------------


class TestMisbehavingHookIntegration:
    """Verify workflow completes successfully despite hook exception."""

    async def test_workflow_completes_with_misbehaving_hook(self) -> None:
        """Misbehaving hook raises on every event but workflow still succeeds."""
        bad_hook = _MisbehavingHook()
        executor = _build_executor({"step-1": "ok"}, hooks=[bad_hook])
        workflow = _simple_workflow()

        result = await executor.execute(workflow, inputs={})

        assert result["step_results"]["step-1"] == "ok"

    async def test_good_hook_still_records_alongside_bad_hook(self) -> None:
        """A recording hook receives events even when a misbehaving hook is also registered."""
        bad_hook = _MisbehavingHook()
        good_hook = _RecordingHook()
        executor = _build_executor({"step-1": "ok"}, hooks=[bad_hook, good_hook])
        workflow = _simple_workflow()

        result = await executor.execute(workflow, inputs={})

        assert result["step_results"]["step-1"] == "ok"
        method_names = [name for name, _ in good_hook.calls]
        assert "on_workflow_start" in method_names
        assert "on_workflow_end" in method_names


# ---------------------------------------------------------------------------
# 5.7 — Streaming execution with hooks
# ---------------------------------------------------------------------------


class TestStreamingHooks:
    """Verify events are dispatched during execute_stream()."""

    async def test_stream_emits_lifecycle_events(self) -> None:
        """execute_stream() yields WORKFLOW_START, STEP_START, STEP_END, WORKFLOW_END."""
        hook = _RecordingHook()
        executor = _build_executor({"step-1": "ok"}, hooks=[hook])
        workflow = _simple_workflow()

        events = []
        async for event in executor.execute_stream(workflow, inputs={}):
            events.append(event)

        event_types = [e.event_type for e in events]
        assert EventType.WORKFLOW_START in event_types
        assert EventType.STEP_START in event_types
        assert EventType.STEP_END in event_types
        assert EventType.WORKFLOW_END in event_types

    async def test_stream_events_in_correct_order(self) -> None:
        """Streaming events follow the same lifecycle order as execute()."""
        hook = _RecordingHook()
        executor = _build_executor({"step-1": "ok"}, hooks=[hook])
        workflow = _simple_workflow()

        events = []
        async for event in executor.execute_stream(workflow, inputs={}):
            events.append(event)

        event_types = [e.event_type for e in events]
        wf_start_idx = event_types.index(EventType.WORKFLOW_START)
        step_start_idx = event_types.index(EventType.STEP_START)
        step_end_idx = event_types.index(EventType.STEP_END)
        wf_end_idx = event_types.index(EventType.WORKFLOW_END)
        assert wf_start_idx < step_start_idx < step_end_idx < wf_end_idx

    async def test_stream_hook_also_records_events(self) -> None:
        """The recording hook receives events during streaming execution."""
        hook = _RecordingHook()
        executor = _build_executor({"step-1": "ok"}, hooks=[hook])
        workflow = _simple_workflow()

        async for _ in executor.execute_stream(workflow, inputs={}):
            pass

        method_names = [name for name, _ in hook.calls]
        assert "on_workflow_start" in method_names
        assert "on_step_start" in method_names
        assert "on_step_end" in method_names
        assert "on_workflow_end" in method_names


# ---------------------------------------------------------------------------
# 5.8 — context.deps.lifecycle_hooks returns LifecycleHookManager
# ---------------------------------------------------------------------------


class TestLifecycleHooksDI:
    """Verify context.deps.lifecycle_hooks returns the LifecycleHookManager instance."""

    async def test_lifecycle_hooks_contains_hook_manager(self) -> None:
        """context.deps.lifecycle_hooks is a LifecycleHookManager instance."""
        capture_prim = _ContextCapturePrimitive()
        registry = PrimitiveRegistry()
        registry.register("llm", capture_prim)
        hook = _RecordingHook()
        executor = WorkflowExecutor(
            registry, deps=DefaultDependencies(lifecycle_hooks=LifecycleHookManager([hook]))
        )
        workflow = _simple_workflow()

        await executor.execute(workflow, inputs={})

        assert capture_prim.captured_hooks is not None
        assert isinstance(capture_prim.captured_hooks, LifecycleHookManager)

    async def test_lifecycle_hooks_is_not_raw_list_of_user_hooks(self) -> None:
        """context.deps.lifecycle_hooks is the manager, not a raw user hook."""
        capture_prim = _ContextCapturePrimitive()
        registry = PrimitiveRegistry()
        registry.register("llm", capture_prim)
        hook = _RecordingHook()
        executor = WorkflowExecutor(
            registry, deps=DefaultDependencies(lifecycle_hooks=LifecycleHookManager([hook]))
        )
        workflow = _simple_workflow()

        await executor.execute(workflow, inputs={})

        # The value should be a LifecycleHookManager, not the raw _RecordingHook
        assert capture_prim.captured_hooks is not None
        assert not isinstance(capture_prim.captured_hooks, _RecordingHook)


# ---------------------------------------------------------------------------
# 5.9 — Hooks disabled (empty list)
# ---------------------------------------------------------------------------


class TestNoHooksExecution:
    """Verify workflow executes normally with no hooks."""

    async def test_execute_with_no_hooks(self) -> None:
        """Workflow completes successfully when hooks list is empty."""
        executor = _build_executor({"step-1": "ok"}, hooks=[])
        workflow = _simple_workflow()

        result = await executor.execute(workflow, inputs={})

        assert result["step_results"]["step-1"] == "ok"

    async def test_execute_with_hooks_none(self) -> None:
        """Workflow completes successfully when hooks is None (default)."""
        registry = PrimitiveRegistry()
        registry.register("llm", _StepDispatchPrimitive({"step-1": "ok"}))
        executor = WorkflowExecutor(registry)
        workflow = _simple_workflow()

        result = await executor.execute(workflow, inputs={})

        assert result["step_results"]["step-1"] == "ok"

    async def test_stream_with_no_hooks(self) -> None:
        """Streaming execution completes with no hooks registered."""
        executor = _build_executor({"step-1": "ok"}, hooks=[])
        workflow = _simple_workflow()

        events = []
        async for event in executor.execute_stream(workflow, inputs={}):
            events.append(event)

        event_types = [e.event_type for e in events]
        assert EventType.WORKFLOW_START in event_types
        assert EventType.WORKFLOW_END in event_types
