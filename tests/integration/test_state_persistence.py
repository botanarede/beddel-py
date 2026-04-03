"""Integration tests for state persistence & checkpoints (Story 6.3, Task 5).

Tests the full pipeline: ExecutionContext → execute steps → checkpoint →
new context → restore → verify state matches. Also covers HOTL integration,
durable execution coexistence, concurrent writes, and domain isolation.

AC #7: IEventStore events and IStateStore checkpoints coexist.
AC #10: checkpoint/resume round-trip, state integrity, concurrent writes,
        InterruptibleContext integration, JSONFileStateStore file I/O,
        error handling.
AC #11: All 4 validation gates pass.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path

import pytest

from beddel.adapters.event_store import InMemoryEventStore
from beddel.adapters.state_store import InMemoryStateStore, JSONFileStateStore
from beddel.domain.models import DefaultDependencies, ExecutionContext

# ---------------------------------------------------------------------------
# 5.1 Full pipeline: create → execute → checkpoint → restore → verify
# ---------------------------------------------------------------------------


class TestFullPipelineCheckpointRestore:
    """Full pipeline integration: context with real data round-trips through checkpoint."""

    @pytest.mark.asyncio
    async def test_full_pipeline_inmemory(self) -> None:
        """InMemoryStateStore: create context → set results → checkpoint → restore."""
        store = InMemoryStateStore()
        deps = DefaultDependencies(state_store=store)

        # --- Create context with inputs and simulate step execution ---
        ctx = ExecutionContext(
            workflow_id="wf-pipeline-1",
            inputs={"prompt": "summarize this", "max_tokens": 100},
            deps=deps,
        )
        ctx.step_results["llm-step"] = {"text": "Summary of the document."}
        ctx.step_results["output-step"] = {"formatted": True}
        ctx.metadata["run_id"] = "run-abc-123"
        ctx.metadata["attempt"] = 1
        ctx.current_step_id = "guardrail-step"

        # --- Checkpoint ---
        await ctx.checkpoint(state_store=store)

        # --- Create a brand-new context and restore ---
        ctx2 = ExecutionContext(workflow_id="wf-blank")
        restored = await ctx2.restore_from_store("wf-pipeline-1", store)

        assert restored is True
        assert ctx2.workflow_id == "wf-pipeline-1"
        assert ctx2.inputs == {"prompt": "summarize this", "max_tokens": 100}
        assert ctx2.step_results["llm-step"] == {"text": "Summary of the document."}
        assert ctx2.step_results["output-step"] == {"formatted": True}
        assert ctx2.metadata["run_id"] == "run-abc-123"
        assert ctx2.metadata["attempt"] == 1
        assert ctx2.current_step_id == "guardrail-step"

    @pytest.mark.asyncio
    async def test_full_pipeline_json_file(self, tmp_path: Path) -> None:
        """JSONFileStateStore: full pipeline with real file I/O."""
        store = JSONFileStateStore(tmp_path / "checkpoints")

        ctx = ExecutionContext(
            workflow_id="wf-pipeline-2",
            inputs={"query": "What is beddel?"},
        )
        ctx.step_results["step-1"] = {"answer": "An agentic workflow SDK."}
        ctx.step_results["step-2"] = {"score": 0.95}
        ctx.metadata["model"] = "gpt-4o"
        ctx.current_step_id = "step-3"

        await ctx.checkpoint(state_store=store)

        # Verify file exists on disk
        state_file = tmp_path / "checkpoints" / "wf-pipeline-2.json"
        assert state_file.exists()
        on_disk = json.loads(state_file.read_text())
        assert on_disk["workflow_id"] == "wf-pipeline-2"

        # Restore into fresh context
        ctx2 = ExecutionContext(workflow_id="wf-new")
        restored = await ctx2.restore_from_store("wf-pipeline-2", store)

        assert restored is True
        assert ctx2.workflow_id == "wf-pipeline-2"
        assert ctx2.inputs == {"query": "What is beddel?"}
        assert ctx2.step_results["step-1"] == {"answer": "An agentic workflow SDK."}
        assert ctx2.step_results["step-2"] == {"score": 0.95}
        assert ctx2.metadata["model"] == "gpt-4o"
        assert ctx2.current_step_id == "step-3"

    @pytest.mark.asyncio
    async def test_full_pipeline_cross_instance_json(self, tmp_path: Path) -> None:
        """Checkpoint with one JSONFileStateStore instance, restore with another."""
        state_dir = tmp_path / "cross-instance"

        store1 = JSONFileStateStore(state_dir)
        ctx = ExecutionContext(
            workflow_id="wf-cross",
            inputs={"data": [1, 2, 3]},
        )
        ctx.step_results["s1"] = "done"
        await ctx.checkpoint(state_store=store1)

        # New store instance, same directory
        store2 = JSONFileStateStore(state_dir)
        ctx2 = ExecutionContext(workflow_id="wf-blank")
        restored = await ctx2.restore_from_store("wf-cross", store2)

        assert restored is True
        assert ctx2.inputs == {"data": [1, 2, 3]}
        assert ctx2.step_results["s1"] == "done"


# ---------------------------------------------------------------------------
# 5.2 HOTL integration: suspended flag preserved through checkpoint/restore
# ---------------------------------------------------------------------------


class TestHOTLIntegration:
    """HOTL pause/resume: suspended flag survives checkpoint round-trip."""

    @pytest.mark.asyncio
    async def test_suspended_flag_preserved_inmemory(self) -> None:
        """InMemoryStateStore: suspend → checkpoint → restore → suspended is True."""
        store = InMemoryStateStore()

        ctx = ExecutionContext(workflow_id="wf-hotl-1", inputs={"approval": "pending"})
        ctx.step_results["pre-approval"] = {"status": "ok"}
        ctx.current_step_id = "approval-gate"
        ctx.suspended = True

        await ctx.checkpoint(state_store=store)

        ctx2 = ExecutionContext(workflow_id="wf-blank")
        restored = await ctx2.restore_from_store("wf-hotl-1", store)

        assert restored is True
        assert ctx2.suspended is True
        assert ctx2.current_step_id == "approval-gate"
        assert ctx2.step_results["pre-approval"] == {"status": "ok"}

    @pytest.mark.asyncio
    async def test_suspended_flag_preserved_json_file(self, tmp_path: Path) -> None:
        """JSONFileStateStore: suspend → checkpoint → restore → suspended is True."""
        store = JSONFileStateStore(tmp_path / "hotl-state")

        ctx = ExecutionContext(workflow_id="wf-hotl-2")
        ctx.metadata["approval_request"] = "Please review output"
        ctx.suspended = True

        await ctx.checkpoint(state_store=store)

        # Verify on disk
        on_disk = json.loads((tmp_path / "hotl-state" / "wf-hotl-2.json").read_text())
        assert on_disk["suspended"] is True

        # Restore
        ctx2 = ExecutionContext(workflow_id="wf-blank")
        restored = await ctx2.restore_from_store("wf-hotl-2", store)

        assert restored is True
        assert ctx2.suspended is True
        assert ctx2.metadata["approval_request"] == "Please review output"

    @pytest.mark.asyncio
    async def test_not_suspended_by_default(self) -> None:
        """Restored context has suspended=False when original was not suspended."""
        store = InMemoryStateStore()

        ctx = ExecutionContext(workflow_id="wf-hotl-3")
        # suspended defaults to False — don't set it
        await ctx.checkpoint(state_store=store)

        ctx2 = ExecutionContext(workflow_id="wf-blank")
        await ctx2.restore_from_store("wf-hotl-3", store)

        assert ctx2.suspended is False


# ---------------------------------------------------------------------------
# 5.3 Durable execution integration: IEventStore + IStateStore coexistence
# ---------------------------------------------------------------------------


class TestDurableExecutionIntegration:
    """IEventStore events and IStateStore checkpoints coexist (AC #7)."""

    @pytest.mark.asyncio
    async def test_event_store_position_in_checkpoint(self) -> None:
        """Checkpoint state includes _event_store_position metadata key."""
        state_store = InMemoryStateStore()
        event_store = InMemoryEventStore()

        # Simulate durable execution: append events
        await event_store.append("wf-durable-1", "s1", {"result": "r1"})
        await event_store.append("wf-durable-1", "s2", {"result": "r2"})
        await event_store.append("wf-durable-1", "s3", {"result": "r3"})

        # Context tracks event store position
        ctx = ExecutionContext(
            workflow_id="wf-durable-1",
            inputs={"task": "durable test"},
        )
        ctx.step_results["s1"] = "r1"
        ctx.step_results["s2"] = "r2"
        ctx.step_results["s3"] = "r3"
        ctx.metadata["_event_store_position"] = 3

        # Checkpoint
        await ctx.checkpoint(state_store=state_store)

        # Verify checkpoint contains position
        loaded = await state_store.load("wf-durable-1")
        assert loaded is not None
        assert loaded["event_store_position"] == 3

        # Restore into new context
        ctx2 = ExecutionContext(workflow_id="wf-blank")
        await ctx2.restore_from_store("wf-durable-1", state_store)

        assert ctx2.metadata["_event_store_position"] == 3

        # Events still accessible from event store
        events = await event_store.load("wf-durable-1")
        assert len(events) == 3
        assert [e["step_id"] for e in events] == ["s1", "s2", "s3"]

    @pytest.mark.asyncio
    async def test_event_store_and_state_store_independent(self) -> None:
        """Deleting state checkpoint doesn't affect event store, and vice versa."""
        state_store = InMemoryStateStore()
        event_store = InMemoryEventStore()

        await event_store.append("wf-indep", "s1", {"result": "r1"})

        ctx = ExecutionContext(workflow_id="wf-indep")
        ctx.step_results["s1"] = "r1"
        ctx.metadata["_event_store_position"] = 1
        await ctx.checkpoint(state_store=state_store)

        # Delete state checkpoint — events unaffected
        await state_store.delete("wf-indep")
        assert await state_store.load("wf-indep") is None
        events = await event_store.load("wf-indep")
        assert len(events) == 1

        # Truncate events — state store unaffected (re-save first)
        await state_store.save("wf-indep", {"workflow_id": "wf-indep", "inputs": {}})
        await event_store.truncate("wf-indep")
        assert await event_store.load("wf-indep") == []
        assert await state_store.load("wf-indep") is not None

    @pytest.mark.asyncio
    async def test_checkpoint_with_zero_position(self) -> None:
        """Position 0 (no events yet) round-trips correctly."""
        store = InMemoryStateStore()

        ctx = ExecutionContext(workflow_id="wf-zero-pos")
        ctx.metadata["_event_store_position"] = 0
        await ctx.checkpoint(state_store=store)

        ctx2 = ExecutionContext(workflow_id="wf-blank")
        await ctx2.restore_from_store("wf-zero-pos", store)

        assert ctx2.metadata["_event_store_position"] == 0

    @pytest.mark.asyncio
    async def test_json_file_durable_coexistence(self, tmp_path: Path) -> None:
        """JSONFileStateStore + InMemoryEventStore coexist for crash recovery."""
        state_store = JSONFileStateStore(tmp_path / "durable-state")
        event_store = InMemoryEventStore()

        await event_store.append("wf-crash", "s1", {"result": "ok"})
        await event_store.append("wf-crash", "s2", {"result": "ok"})

        ctx = ExecutionContext(workflow_id="wf-crash", inputs={"retry": True})
        ctx.step_results["s1"] = "ok"
        ctx.step_results["s2"] = "ok"
        ctx.metadata["_event_store_position"] = 2
        await ctx.checkpoint(state_store=state_store)

        # Simulate crash recovery: new context, restore from file
        ctx2 = ExecutionContext(workflow_id="wf-blank")
        restored = await ctx2.restore_from_store("wf-crash", state_store)

        assert restored is True
        assert ctx2.metadata["_event_store_position"] == 2
        assert ctx2.step_results == {"s1": "ok", "s2": "ok"}


# ---------------------------------------------------------------------------
# 5.4 Concurrent writes: two JSONFileStateStore instances, same workflow_id
# ---------------------------------------------------------------------------


class TestConcurrentWrites:
    """Concurrent writes to same workflow_id — verify no corruption (file locking)."""

    @pytest.mark.asyncio
    async def test_concurrent_writes_two_instances(self, tmp_path: Path) -> None:
        """Two JSONFileStateStore instances writing to same workflow_id concurrently."""
        state_dir = tmp_path / "concurrent"

        store_a = JSONFileStateStore(state_dir)
        store_b = JSONFileStateStore(state_dir)

        async def write_a() -> None:
            for i in range(10):
                await store_a.save("wf-race", {"writer": "A", "seq": i})

        async def write_b() -> None:
            for i in range(10):
                await store_b.save("wf-race", {"writer": "B", "seq": i})

        await asyncio.gather(write_a(), write_b())

        # File must be valid JSON — no corruption
        state_file = state_dir / "wf-race.json"
        assert state_file.exists()
        on_disk = json.loads(state_file.read_text())
        assert on_disk["writer"] in ("A", "B")
        assert isinstance(on_disk["seq"], int)

        # Load via store also works
        loaded = await store_a.load("wf-race")
        assert loaded is not None
        assert loaded["writer"] in ("A", "B")

    @pytest.mark.asyncio
    async def test_concurrent_writes_gather(self, tmp_path: Path) -> None:
        """asyncio.gather with multiple saves — no corruption."""
        store = JSONFileStateStore(tmp_path / "gather-test")

        tasks = [store.save("wf-gather", {"value": i, "data": f"payload-{i}"}) for i in range(20)]
        await asyncio.gather(*tasks)

        # File must be valid JSON
        state_file = tmp_path / "gather-test" / "wf-gather.json"
        assert state_file.exists()
        on_disk = json.loads(state_file.read_text())
        assert "value" in on_disk
        assert isinstance(on_disk["value"], int)

    @pytest.mark.asyncio
    async def test_concurrent_different_workflows(self, tmp_path: Path) -> None:
        """Concurrent writes to different workflow_ids — all succeed independently."""
        store = JSONFileStateStore(tmp_path / "multi-wf")

        tasks = [store.save(f"wf-{i}", {"id": i, "data": f"workflow-{i}"}) for i in range(10)]
        await asyncio.gather(*tasks)

        for i in range(10):
            loaded = await store.load(f"wf-{i}")
            assert loaded is not None
            assert loaded["id"] == i
            assert loaded["data"] == f"workflow-{i}"


# ---------------------------------------------------------------------------
# 5.6 Domain isolation: no adapter imports in domain core
# ---------------------------------------------------------------------------


class TestDomainIsolation:
    """Verify domain core never imports from adapters."""

    def test_no_adapter_imports_in_domain(self) -> None:
        result = subprocess.run(
            [
                "grep",
                "-r",
                "from beddel.adapters",
                "src/beddel-py/src/beddel/domain/",
            ],
            capture_output=True,
            text=True,
        )
        assert result.stdout == "", f"Domain core imports from adapters:\n{result.stdout}"
