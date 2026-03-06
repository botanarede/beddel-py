"""Unit tests for beddel.adapters.hooks module."""

from __future__ import annotations

from typing import Any

from beddel.adapters.hooks import LifecycleHookManager
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


# ---------------------------------------------------------------------------
# Tests: add_hook / remove_hook (subtask 4.3, 4.8)
# ---------------------------------------------------------------------------


class TestAddRemoveHooks:
    """Hooks are added and removed correctly."""

    async def test_add_hook_registers_handler(self) -> None:
        manager = LifecycleHookManager()
        hook = _RecordingHook()
        manager.add_hook(hook)
        await manager.on_step_start("s1", "llm")
        assert len(hook.calls) == 1

    async def test_remove_hook_unregisters_handler(self) -> None:
        hook = _RecordingHook()
        manager = LifecycleHookManager([hook])
        manager.remove_hook(hook)
        await manager.on_step_start("s1", "llm")
        assert len(hook.calls) == 0

    async def test_constructor_accepts_initial_hooks(self) -> None:
        hook = _RecordingHook()
        manager = LifecycleHookManager([hook])
        await manager.on_step_end("s1", "done")
        assert len(hook.calls) == 1

    def test_remove_hook_with_non_registered_hook_no_error(self) -> None:
        """Removing a hook that was never added does not raise."""
        manager = LifecycleHookManager()
        unregistered = _RecordingHook()
        manager.remove_hook(unregistered)  # should not raise


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
        assert len(hook.calls) == 6

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
        method_names = [name for name, _ in hook.calls]
        assert method_names == [
            "on_workflow_start",
            "on_workflow_end",
            "on_step_start",
            "on_step_end",
            "on_error",
            "on_retry",
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
