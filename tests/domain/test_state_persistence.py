"""Unit tests for InterruptibleContext checkpoint/restore_from_store (Story 6.3, Task 4).

Tests: checkpoint round-trip, restore_from_store with existing state,
restore_from_store with missing state returns False, corrupted state raises StateError.
"""

from __future__ import annotations

import pytest

from beddel.adapters.state_store import InMemoryStateStore
from beddel.domain.errors import StateError
from beddel.domain.models import ExecutionContext

# ---------------------------------------------------------------------------
# checkpoint() round-trip (Task 4.1)
# ---------------------------------------------------------------------------


class TestCheckpointRoundTrip:
    """checkpoint() serializes and persists state via IStateStore."""

    @pytest.mark.asyncio
    async def test_checkpoint_persists_state(self) -> None:
        store = InMemoryStateStore()
        ctx = ExecutionContext(workflow_id="wf-cp-1", inputs={"x": 1})
        ctx.step_results["s1"] = "done"
        ctx.current_step_id = "s2"

        await ctx.checkpoint(state_store=store)

        loaded = await store.load("wf-cp-1")
        assert loaded is not None
        assert loaded["workflow_id"] == "wf-cp-1"
        assert loaded["inputs"] == {"x": 1}
        assert loaded["step_results"] == {"s1": "done"}
        assert loaded["current_step_id"] == "s2"

    @pytest.mark.asyncio
    async def test_checkpoint_without_store_does_not_raise(self) -> None:
        ctx = ExecutionContext(workflow_id="wf-cp-2")
        # Should not raise — just serializes without persisting
        await ctx.checkpoint(state_store=None)

    @pytest.mark.asyncio
    async def test_checkpoint_captures_suspended_flag(self) -> None:
        store = InMemoryStateStore()
        ctx = ExecutionContext(workflow_id="wf-cp-3")
        ctx.suspended = True

        await ctx.checkpoint(state_store=store)

        loaded = await store.load("wf-cp-3")
        assert loaded is not None
        assert loaded["suspended"] is True

    @pytest.mark.asyncio
    async def test_checkpoint_round_trip_restore(self) -> None:
        """Full round-trip: checkpoint → new context → restore_from_store."""
        store = InMemoryStateStore()
        ctx = ExecutionContext(
            workflow_id="wf-rt-1",
            inputs={"prompt": "hello"},
        )
        ctx.step_results["step-a"] = {"text": "world"}
        ctx.metadata["_event_store_position"] = 5
        ctx.current_step_id = "step-b"
        ctx.suspended = True

        await ctx.checkpoint(state_store=store)

        ctx2 = ExecutionContext(workflow_id="wf-new")
        result = await ctx2.restore_from_store("wf-rt-1", store)

        assert result is True
        assert ctx2.workflow_id == "wf-rt-1"
        assert ctx2.inputs == {"prompt": "hello"}
        assert ctx2.step_results == {"step-a": {"text": "world"}}
        assert ctx2.current_step_id == "step-b"
        assert ctx2.suspended is True
        assert ctx2.metadata["_event_store_position"] == 5


# ---------------------------------------------------------------------------
# restore_from_store() with existing state (Task 4.2)
# ---------------------------------------------------------------------------


class TestRestoreFromStore:
    """restore_from_store() loads and restores persisted state."""

    @pytest.mark.asyncio
    async def test_restore_existing_state_returns_true(self) -> None:
        store = InMemoryStateStore()
        state = {
            "workflow_id": "wf-exist",
            "inputs": {"a": 1},
            "step_results": {"s1": "ok"},
            "metadata": {},
            "current_step_id": "s2",
            "suspended": False,
            "event_store_position": 0,
        }
        await store.save("wf-exist", state)

        ctx = ExecutionContext(workflow_id="wf-blank")
        result = await ctx.restore_from_store("wf-exist", store)

        assert result is True
        assert ctx.workflow_id == "wf-exist"
        assert ctx.inputs == {"a": 1}
        assert ctx.step_results == {"s1": "ok"}

    @pytest.mark.asyncio
    async def test_restore_missing_state_returns_false(self) -> None:
        store = InMemoryStateStore()
        ctx = ExecutionContext(workflow_id="wf-blank")
        result = await ctx.restore_from_store("wf-nonexistent", store)

        assert result is False
        # Context should remain unchanged
        assert ctx.workflow_id == "wf-blank"

    @pytest.mark.asyncio
    async def test_restore_preserves_event_store_position(self) -> None:
        store = InMemoryStateStore()
        state = {
            "workflow_id": "wf-pos",
            "inputs": {},
            "step_results": {},
            "metadata": {},
            "current_step_id": None,
            "suspended": False,
            "event_store_position": 42,
        }
        await store.save("wf-pos", state)

        ctx = ExecutionContext(workflow_id="wf-blank")
        await ctx.restore_from_store("wf-pos", store)
        assert ctx.metadata["_event_store_position"] == 42


# ---------------------------------------------------------------------------
# Corrupted state raises StateError (Task 4.2)
# ---------------------------------------------------------------------------


class TestCorruptedStateRaisesStateError:
    """restore_from_store() raises StateError on corrupted state."""

    @pytest.mark.asyncio
    async def test_missing_workflow_id_key(self) -> None:
        store = InMemoryStateStore()
        # Missing 'workflow_id' key
        await store.save("wf-bad", {"inputs": {}, "step_results": {}, "metadata": {}})

        ctx = ExecutionContext(workflow_id="wf-blank")
        with pytest.raises(StateError) as exc_info:
            await ctx.restore_from_store("wf-bad", store)
        assert exc_info.value.code == "BEDDEL-STATE-943"
        assert "missing keys" in exc_info.value.message

    @pytest.mark.asyncio
    async def test_missing_inputs_key(self) -> None:
        store = InMemoryStateStore()
        await store.save("wf-bad2", {"workflow_id": "x", "step_results": {}, "metadata": {}})

        ctx = ExecutionContext(workflow_id="wf-blank")
        with pytest.raises(StateError) as exc_info:
            await ctx.restore_from_store("wf-bad2", store)
        assert exc_info.value.code == "BEDDEL-STATE-943"

    @pytest.mark.asyncio
    async def test_missing_step_results_key(self) -> None:
        store = InMemoryStateStore()
        await store.save("wf-bad3", {"workflow_id": "x", "inputs": {}, "metadata": {}})

        ctx = ExecutionContext(workflow_id="wf-blank")
        with pytest.raises(StateError) as exc_info:
            await ctx.restore_from_store("wf-bad3", store)
        assert exc_info.value.code == "BEDDEL-STATE-943"

    @pytest.mark.asyncio
    async def test_missing_metadata_key(self) -> None:
        store = InMemoryStateStore()
        await store.save("wf-bad4", {"workflow_id": "x", "inputs": {}, "step_results": {}})

        ctx = ExecutionContext(workflow_id="wf-blank")
        with pytest.raises(StateError) as exc_info:
            await ctx.restore_from_store("wf-bad4", store)
        assert exc_info.value.code == "BEDDEL-STATE-943"

    @pytest.mark.asyncio
    async def test_empty_dict_raises_state_error(self) -> None:
        store = InMemoryStateStore()
        await store.save("wf-empty", {})

        ctx = ExecutionContext(workflow_id="wf-blank")
        with pytest.raises(StateError) as exc_info:
            await ctx.restore_from_store("wf-empty", store)
        assert exc_info.value.code == "BEDDEL-STATE-943"
