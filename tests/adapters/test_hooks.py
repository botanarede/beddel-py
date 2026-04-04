"""Unit tests for beddel.adapters.hooks module."""

from __future__ import annotations

import asyncio
from typing import Any

from beddel.adapters.hooks import LifecycleHookManager
from beddel.domain.models import Decision
from beddel.domain.ports import ILifecycleHook

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


class _RecordingHook(ILifecycleHook):
    """Async hook that records all calls for assertions."""

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

    async def on_decision(self, decision: Decision) -> None:
        self.calls.append(("on_decision", decision))


class _SyncRecordingHook(ILifecycleHook):
    """Sync hook (plain def, NOT async def) that records calls."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def on_workflow_start(self, workflow_id: str, inputs: dict[str, Any]) -> None:  # type: ignore[override]
        self.calls.append(("on_workflow_start", (workflow_id, inputs)))

    def on_workflow_end(self, workflow_id: str, result: dict[str, Any]) -> None:  # type: ignore[override]
        self.calls.append(("on_workflow_end", (workflow_id, result)))

    def on_step_start(self, step_id: str, primitive: str) -> None:  # type: ignore[override]
        self.calls.append(("on_step_start", (step_id, primitive)))

    def on_step_end(self, step_id: str, result: Any) -> None:  # type: ignore[override]
        self.calls.append(("on_step_end", (step_id, result)))

    def on_error(self, step_id: str, error: Exception) -> None:  # type: ignore[override]
        self.calls.append(("on_error", (step_id, error)))

    def on_retry(self, step_id: str, attempt: int, error: Exception) -> None:  # type: ignore[override]
        self.calls.append(("on_retry", (step_id, attempt, error)))

    def on_decision(self, decision: Decision) -> None:  # type: ignore[override]
        self.calls.append(("on_decision", decision))


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

    async def on_decision(self, decision: Decision) -> None:
        raise RuntimeError("boom")


# ---------------------------------------------------------------------------
# Tests: Interface compliance (AC 2)
# ---------------------------------------------------------------------------


class TestInterfaceCompliance:
    """LifecycleHookManager implements the ILifecycleHook port interface."""

    def test_is_subclass_of_ilifecyclehook(self) -> None:
        assert issubclass(LifecycleHookManager, ILifecycleHook)

    def test_instance_is_ilifecyclehook(self) -> None:
        manager = LifecycleHookManager()
        assert isinstance(manager, ILifecycleHook)

    def test_is_subclass_of_ihookmanager(self) -> None:
        """LifecycleHookManager structurally satisfies IHookManager."""
        assert hasattr(LifecycleHookManager, "add_hook")
        assert hasattr(LifecycleHookManager, "remove_hook")
        assert hasattr(LifecycleHookManager, "on_decision")

    def test_instance_is_ihookmanager(self) -> None:
        manager = LifecycleHookManager()
        assert hasattr(manager, "add_hook")
        assert hasattr(manager, "remove_hook")
        assert hasattr(manager, "on_decision")


# ---------------------------------------------------------------------------
# Tests: No hooks registered (subtask 4.2)
# ---------------------------------------------------------------------------


class TestNoHooks:
    """All 6 event methods are callable with no hooks registered."""

    async def test_on_workflow_start_no_hooks(self) -> None:
        manager = LifecycleHookManager()
        await manager.on_workflow_start("wf-1", {"key": "val"})

    async def test_on_workflow_end_no_hooks(self) -> None:
        manager = LifecycleHookManager()
        await manager.on_workflow_end("wf-1", {"result": 42})

    async def test_on_step_start_no_hooks(self) -> None:
        manager = LifecycleHookManager()
        await manager.on_step_start("step-1", "llm")

    async def test_on_step_end_no_hooks(self) -> None:
        manager = LifecycleHookManager()
        await manager.on_step_end("step-1", "ok")

    async def test_on_error_no_hooks(self) -> None:
        manager = LifecycleHookManager()
        await manager.on_error("step-1", RuntimeError("fail"))

    async def test_on_retry_no_hooks(self) -> None:
        manager = LifecycleHookManager()
        await manager.on_retry("step-1", 1, RuntimeError("fail"))

    async def test_on_decision_no_hooks(self) -> None:
        manager = LifecycleHookManager()
        d = Decision(id="", intent="use-cache", options=["skip-cache"], reasoning="faster")
        await manager.on_decision(d)


# ---------------------------------------------------------------------------
# Tests: add_hook / remove_hook (subtask 4.3, 4.8)
# ---------------------------------------------------------------------------


class TestAddRemoveHooks:
    """Hooks are added and removed correctly."""

    async def test_add_hook_registers_handler(self) -> None:
        manager = LifecycleHookManager()
        hook = _RecordingHook()
        await manager.add_hook(hook)
        await manager.on_step_start("s1", "llm")
        assert len(hook.calls) == 1

    async def test_remove_hook_unregisters_handler(self) -> None:
        hook = _RecordingHook()
        manager = LifecycleHookManager([hook])
        await manager.remove_hook(hook)
        await manager.on_step_start("s1", "llm")
        assert len(hook.calls) == 0

    async def test_constructor_accepts_initial_hooks(self) -> None:
        hook = _RecordingHook()
        manager = LifecycleHookManager([hook])
        await manager.on_step_end("s1", "done")
        assert len(hook.calls) == 1

    async def test_remove_hook_with_non_registered_hook_no_error(self) -> None:
        """Removing a hook that was never added does not raise."""
        manager = LifecycleHookManager()
        unregistered = _RecordingHook()
        await manager.remove_hook(unregistered)  # should not raise


# ---------------------------------------------------------------------------
# Tests: Multiple hook dispatch (subtask 4.4)
# ---------------------------------------------------------------------------


class TestMultipleHookDispatch:
    """All registered hooks receive each event."""

    async def test_all_hooks_receive_event(self) -> None:
        hook_a = _RecordingHook()
        hook_b = _RecordingHook()
        manager = LifecycleHookManager([hook_a, hook_b])
        await manager.on_step_start("s1", "llm")
        assert len(hook_a.calls) == 1
        assert len(hook_b.calls) == 1

    async def test_hooks_receive_same_arguments(self) -> None:
        hook_a = _RecordingHook()
        hook_b = _RecordingHook()
        manager = LifecycleHookManager([hook_a, hook_b])
        await manager.on_workflow_start("wf-1", {"x": 1})
        assert hook_a.calls[0] == ("on_workflow_start", ("wf-1", {"x": 1}))
        assert hook_b.calls[0] == ("on_workflow_start", ("wf-1", {"x": 1}))


# ---------------------------------------------------------------------------
# Tests: Misbehaving hook (subtask 4.5, AC 6)
# ---------------------------------------------------------------------------


class TestMisbehavingHook:
    """Exception in one hook does not prevent other hooks from being called."""

    async def test_error_in_first_hook_does_not_block_second(self) -> None:
        bad = _MisbehavingHook()
        good = _RecordingHook()
        manager = LifecycleHookManager([bad, good])
        await manager.on_step_start("s1", "llm")
        assert len(good.calls) == 1

    async def test_error_in_middle_hook_does_not_block_others(self) -> None:
        first = _RecordingHook()
        bad = _MisbehavingHook()
        last = _RecordingHook()
        manager = LifecycleHookManager([first, bad, last])
        await manager.on_workflow_end("wf-1", {"ok": True})
        assert len(first.calls) == 1
        assert len(last.calls) == 1

    async def test_on_decision_misbehaving_does_not_block(self) -> None:
        bad = _MisbehavingHook()
        good = _RecordingHook()
        manager = LifecycleHookManager([bad, good])
        d = Decision(id="", intent="pick-a", options=["pick-b"], reasoning="reason")
        await manager.on_decision(d)
        assert len(good.calls) == 1
        assert good.calls[0] == ("on_decision", d)


# ---------------------------------------------------------------------------
# Tests: Sync handler support (subtask 4.6, AC 7)
# ---------------------------------------------------------------------------


class TestSyncHandlerSupport:
    """Sync (non-async) handlers are detected and called without await."""

    async def test_sync_hook_receives_events(self) -> None:
        hook = _SyncRecordingHook()
        manager = LifecycleHookManager([hook])
        await manager.on_step_start("s1", "llm")
        assert hook.calls == [("on_step_start", ("s1", "llm"))]

    async def test_sync_hook_all_methods_callable(self) -> None:
        hook = _SyncRecordingHook()
        manager = LifecycleHookManager([hook])
        err = RuntimeError("fail")
        await manager.on_workflow_start("wf", {"a": 1})
        await manager.on_workflow_end("wf", {"b": 2})
        await manager.on_step_start("s", "chat")
        await manager.on_step_end("s", "result")
        await manager.on_error("s", err)
        await manager.on_retry("s", 3, err)
        await manager.on_decision(Decision(id="", intent="d", options=["alt"], reasoning="why"))
        assert len(hook.calls) == 7

    async def test_sync_and_async_hooks_coexist(self) -> None:
        sync_hook = _SyncRecordingHook()
        async_hook = _RecordingHook()
        manager = LifecycleHookManager([sync_hook, async_hook])
        await manager.on_step_end("s1", "done")
        assert len(sync_hook.calls) == 1
        assert len(async_hook.calls) == 1


# ---------------------------------------------------------------------------
# Tests: Async handler support (subtask 4.7, AC 7)
# ---------------------------------------------------------------------------


class TestAsyncHandlerSupport:
    """Async handlers are awaited correctly."""

    async def test_async_hook_receives_events(self) -> None:
        hook = _RecordingHook()
        manager = LifecycleHookManager([hook])
        await manager.on_workflow_start("wf-1", {"key": "val"})
        assert hook.calls == [("on_workflow_start", ("wf-1", {"key": "val"}))]

    async def test_async_hook_all_methods_awaited(self) -> None:
        hook = _RecordingHook()
        manager = LifecycleHookManager([hook])
        err = RuntimeError("fail")
        await manager.on_workflow_start("wf", {"a": 1})
        await manager.on_workflow_end("wf", {"b": 2})
        await manager.on_step_start("s", "chat")
        await manager.on_step_end("s", "result")
        await manager.on_error("s", err)
        await manager.on_retry("s", 3, err)
        await manager.on_decision(Decision(id="", intent="d", options=["alt"], reasoning="reason"))
        method_names = [name for name, _ in hook.calls]
        assert method_names == [
            "on_workflow_start",
            "on_workflow_end",
            "on_step_start",
            "on_step_end",
            "on_error",
            "on_retry",
            "on_decision",
        ]


# ---------------------------------------------------------------------------
# Tests: All 6 event methods dispatch correctly (subtask 4.9)
# ---------------------------------------------------------------------------


class TestAllEventMethods:
    """All 6 lifecycle methods dispatch with correct arguments."""

    async def test_on_workflow_start_dispatches_args(self) -> None:
        hook = _RecordingHook()
        manager = LifecycleHookManager([hook])
        await manager.on_workflow_start("wf-42", {"input": "data"})
        assert hook.calls == [("on_workflow_start", ("wf-42", {"input": "data"}))]

    async def test_on_workflow_end_dispatches_args(self) -> None:
        hook = _RecordingHook()
        manager = LifecycleHookManager([hook])
        await manager.on_workflow_end("wf-42", {"output": "result"})
        assert hook.calls == [("on_workflow_end", ("wf-42", {"output": "result"}))]

    async def test_on_step_start_dispatches_args(self) -> None:
        hook = _RecordingHook()
        manager = LifecycleHookManager([hook])
        await manager.on_step_start("step-7", "llm")
        assert hook.calls == [("on_step_start", ("step-7", "llm"))]

    async def test_on_step_end_dispatches_args(self) -> None:
        hook = _RecordingHook()
        manager = LifecycleHookManager([hook])
        await manager.on_step_end("step-7", {"value": 99})
        assert hook.calls == [("on_step_end", ("step-7", {"value": 99}))]

    async def test_on_error_dispatches_args(self) -> None:
        hook = _RecordingHook()
        manager = LifecycleHookManager([hook])
        err = ValueError("something broke")
        await manager.on_error("step-7", err)
        assert hook.calls == [("on_error", ("step-7", err))]

    async def test_on_retry_dispatches_args(self) -> None:
        hook = _RecordingHook()
        manager = LifecycleHookManager([hook])
        err = TimeoutError("timed out")
        await manager.on_retry("step-7", 2, err)
        assert hook.calls == [("on_retry", ("step-7", 2, err))]

    async def test_on_decision_dispatches_args(self) -> None:
        hook = _RecordingHook()
        manager = LifecycleHookManager([hook])
        d = Decision(
            id="",
            intent="use-gpt4",
            options=["use-claude", "use-llama"],
            reasoning="best quality",
        )
        await manager.on_decision(d)
        assert hook.calls == [("on_decision", d)]


# ---------------------------------------------------------------------------
# Tests: Thread-safety / concurrent hook registration (Story 4.0h, Task 1)
# ---------------------------------------------------------------------------


class TestThreadSafety:
    """Thread-safety tests for concurrent hook registration (Story 4.0h)."""

    async def test_concurrent_add_hook_no_lost_hooks(self) -> None:
        """asyncio.gather adding 50 hooks concurrently loses no appends."""
        manager = LifecycleHookManager()
        hooks = [_RecordingHook() for _ in range(50)]
        await asyncio.gather(*(manager.add_hook(h) for h in hooks))
        assert len(manager._hooks) == 50

    async def test_concurrent_remove_hook_no_errors(self) -> None:
        """asyncio.gather removing 50 hooks concurrently raises no errors."""
        hooks = [_RecordingHook() for _ in range(50)]
        manager = LifecycleHookManager(hooks)
        await asyncio.gather(*(manager.remove_hook(h) for h in hooks))
        assert len(manager._hooks) == 0

    async def test_iteration_stable_during_concurrent_add(self) -> None:
        """Snapshot isolation: hook added during dispatch does NOT receive in-flight event."""
        import asyncio as _asyncio

        class _SlowHook(ILifecycleHook):
            def __init__(self) -> None:
                self.called = False

            async def on_step_start(self, step_id: str, primitive: str) -> None:
                self.called = True
                await _asyncio.sleep(0.05)  # Yield control to event loop

        class _LateHook(ILifecycleHook):
            def __init__(self) -> None:
                self.step_start_calls: list[str] = []

            async def on_step_start(self, step_id: str, primitive: str) -> None:
                self.step_start_calls.append(step_id)

        slow = _SlowHook()
        late = _LateHook()
        manager = LifecycleHookManager([slow])

        async def dispatch_and_add() -> None:
            dispatch_task = _asyncio.create_task(manager.on_step_start("s1", "llm"))
            await _asyncio.sleep(0.01)  # Let dispatch start and take snapshot
            await manager.add_hook(late)  # Add after snapshot taken
            await dispatch_task

        await dispatch_and_add()
        assert slow.called
        assert late.step_start_calls == []  # Late hook missed the in-flight event

        # But late hook DOES receive subsequent events
        await manager.on_step_start("s2", "chat")
        assert late.step_start_calls == ["s2"]

    async def test_iteration_stable_during_concurrent_remove(self) -> None:
        """Removing a hook during dispatch does not cause iteration errors."""
        import asyncio as _asyncio

        class _SlowHook(ILifecycleHook):
            def __init__(self) -> None:
                self.called = False

            async def on_step_end(self, step_id: str, result: Any) -> None:
                self.called = True
                await _asyncio.sleep(0.05)

        slow = _SlowHook()
        victim = _RecordingHook()
        manager = LifecycleHookManager([slow, victim])

        async def dispatch_and_remove() -> None:
            dispatch_task = _asyncio.create_task(manager.on_step_end("s1", "ok"))
            await _asyncio.sleep(0.01)
            await manager.remove_hook(victim)  # Remove during iteration
            await dispatch_task

        await dispatch_and_remove()
        assert slow.called
        # victim was in the snapshot, so it still received the event
        assert len(victim.calls) == 1

    async def test_no_deadlock_hook_adds_hook_during_dispatch(self) -> None:
        """Hook calling add_hook during dispatch does not deadlock.

        Validates that the lock is NOT held during hook execution — only
        during the snapshot copy.  A hook that calls ``manager.add_hook()``
        inside its callback must be able to acquire the lock without
        deadlocking.
        """
        import asyncio as _asyncio

        late = _RecordingHook()

        class _SelfRegisteringHook(ILifecycleHook):
            def __init__(self, mgr: LifecycleHookManager, to_add: ILifecycleHook) -> None:
                self._mgr = mgr
                self._to_add = to_add
                self.called = False

            async def on_step_start(self, step_id: str, primitive: str) -> None:
                self.called = True
                await self._mgr.add_hook(self._to_add)

        manager = LifecycleHookManager()
        registering = _SelfRegisteringHook(manager, late)
        await manager.add_hook(registering)

        # Must complete without deadlock — use wait_for as a safety net
        await _asyncio.wait_for(manager.on_step_start("s1", "llm"), timeout=2.0)
        assert registering.called
        # late was added DURING dispatch, so it missed the in-flight event
        assert late.calls == []

        # But late hook receives subsequent events
        await manager.on_step_start("s2", "chat")
        assert len(late.calls) == 1
        assert late.calls[0] == ("on_step_start", ("s2", "chat"))


# ---------------------------------------------------------------------------
# Tests: Backward-compatible on_decision (Story 7.1, Task 2 — AC #3)
# ---------------------------------------------------------------------------


class _OldStyleAsyncHook(ILifecycleHook):
    """Hook using the old 3-arg on_decision signature."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, list[str], str]] = []

    async def on_decision(self, decision: str, alternatives: list[str], rationale: str) -> None:  # type: ignore[override]
        self.calls.append((decision, alternatives, rationale))


class _OldStyleSyncHook(ILifecycleHook):
    """Sync hook using the old 3-arg on_decision signature."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, list[str], str]] = []

    def on_decision(self, decision: str, alternatives: list[str], rationale: str) -> None:  # type: ignore[override]
        self.calls.append((decision, alternatives, rationale))


class TestBackwardCompatibleOnDecision:
    """Old-style hooks with 3-arg on_decision still work via TypeError fallback."""

    async def test_old_style_async_hook_receives_decision(self) -> None:
        old_hook = _OldStyleAsyncHook()
        manager = LifecycleHookManager([old_hook])
        d = Decision(id="d1", intent="use-cache", options=["skip-cache"], reasoning="faster")
        await manager.on_decision(d)
        assert len(old_hook.calls) == 1
        assert old_hook.calls[0] == ("use-cache", ["skip-cache"], "faster")

    async def test_old_style_sync_hook_receives_decision(self) -> None:
        old_hook = _OldStyleSyncHook()
        manager = LifecycleHookManager([old_hook])
        d = Decision(id="d2", intent="pick-model", options=["gpt4", "claude"], reasoning="cost")
        await manager.on_decision(d)
        assert len(old_hook.calls) == 1
        assert old_hook.calls[0] == ("pick-model", ["gpt4", "claude"], "cost")

    async def test_mixed_old_and_new_hooks(self) -> None:
        old_hook = _OldStyleAsyncHook()
        new_hook = _RecordingHook()
        manager = LifecycleHookManager([old_hook, new_hook])
        d = Decision(id="d3", intent="route", options=["a", "b"], reasoning="perf")
        await manager.on_decision(d)
        # Old hook receives decomposed args
        assert old_hook.calls == [("route", ["a", "b"], "perf")]
        # New hook receives the Decision object
        assert new_hook.calls == [("on_decision", d)]
