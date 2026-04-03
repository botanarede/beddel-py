"""Tests for state store adapters (InMemoryStateStore, JSONFileStateStore)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from beddel.adapters.state_store import InMemoryStateStore, JSONFileStateStore
from beddel.domain.errors import StateError
from beddel.error_codes import (
    STATE_CORRUPTED,
    STATE_DELETE_FAILED,
    STATE_LOAD_FAILED,
    STATE_SAVE_FAILED,
)


class TestInMemoryStateStore:
    """Unit tests for the InMemoryStateStore adapter."""

    @pytest.mark.asyncio
    async def test_save_and_load_round_trip(self) -> None:
        """Save state and load it back — verify content matches."""
        store = InMemoryStateStore()
        state = {"step": "a", "data": [1, 2, 3]}

        await store.save("wf-1", state)
        loaded = await store.load("wf-1")

        assert loaded == state

    @pytest.mark.asyncio
    async def test_load_missing_returns_none(self) -> None:
        """Load for unknown workflow_id returns None."""
        store = InMemoryStateStore()

        result = await store.load("nonexistent")

        assert result is None

    @pytest.mark.asyncio
    async def test_delete_existing(self) -> None:
        """Save state, delete it, verify load returns None."""
        store = InMemoryStateStore()

        await store.save("wf-1", {"step": "a"})
        await store.delete("wf-1")

        assert await store.load("wf-1") is None

    @pytest.mark.asyncio
    async def test_delete_missing_no_op(self) -> None:
        """Delete unknown workflow_id does not raise."""
        store = InMemoryStateStore()

        await store.delete("nonexistent")

    @pytest.mark.asyncio
    async def test_save_overwrites(self) -> None:
        """Saving twice overwrites the previous state."""
        store = InMemoryStateStore()

        await store.save("wf-1", {"v": 1})
        await store.save("wf-1", {"v": 2})

        loaded = await store.load("wf-1")
        assert loaded == {"v": 2}

    @pytest.mark.asyncio
    async def test_load_returns_copy(self) -> None:
        """Loaded state is a copy — mutation doesn't affect store."""
        store = InMemoryStateStore()

        await store.save("wf-1", {"key": "value"})
        loaded = await store.load("wf-1")
        assert loaded is not None
        loaded["key"] = "mutated"

        fresh = await store.load("wf-1")
        assert fresh is not None
        assert fresh["key"] == "value"

    @pytest.mark.asyncio
    async def test_multiple_workflows_isolated(self) -> None:
        """States for different workflow_ids are independent."""
        store = InMemoryStateStore()

        await store.save("wf-1", {"data": "one"})
        await store.save("wf-2", {"data": "two"})

        assert (await store.load("wf-1")) == {"data": "one"}
        assert (await store.load("wf-2")) == {"data": "two"}

        await store.delete("wf-1")
        assert await store.load("wf-1") is None
        assert (await store.load("wf-2")) == {"data": "two"}


class TestJSONFileStateStore:
    """Unit tests for the JSONFileStateStore adapter."""

    @pytest.mark.asyncio
    async def test_save_and_load_round_trip(self, tmp_path: Path) -> None:
        """Save state and load it back — verify content matches."""
        store = JSONFileStateStore(tmp_path / "state")
        state = {"step": "a", "data": [1, 2, 3], "nested": {"x": True}}

        await store.save("wf-1", state)
        loaded = await store.load("wf-1")

        assert loaded == state

    @pytest.mark.asyncio
    async def test_load_missing_returns_none(self, tmp_path: Path) -> None:
        """Load for unknown workflow_id returns None."""
        store = JSONFileStateStore(tmp_path / "state")

        result = await store.load("nonexistent")

        assert result is None

    @pytest.mark.asyncio
    async def test_delete_existing(self, tmp_path: Path) -> None:
        """Save state, delete it, verify load returns None."""
        store = JSONFileStateStore(tmp_path / "state")

        await store.save("wf-1", {"step": "a"})
        await store.delete("wf-1")

        assert await store.load("wf-1") is None
        assert not (tmp_path / "state" / "wf-1.json").exists()

    @pytest.mark.asyncio
    async def test_delete_missing_no_op(self, tmp_path: Path) -> None:
        """Delete unknown workflow_id does not raise."""
        store = JSONFileStateStore(tmp_path / "state")

        await store.delete("nonexistent")

    @pytest.mark.asyncio
    async def test_save_overwrites(self, tmp_path: Path) -> None:
        """Saving twice overwrites the previous state."""
        store = JSONFileStateStore(tmp_path / "state")

        await store.save("wf-1", {"v": 1})
        await store.save("wf-1", {"v": 2})

        loaded = await store.load("wf-1")
        assert loaded == {"v": 2}

    @pytest.mark.asyncio
    async def test_directory_creation(self, tmp_path: Path) -> None:
        """Constructor creates directory if it doesn't exist."""
        state_dir = tmp_path / "nested" / "state"
        assert not state_dir.exists()

        store = JSONFileStateStore(state_dir)

        assert state_dir.exists()
        await store.save("wf-1", {"ok": True})
        assert (state_dir / "wf-1.json").exists()

    @pytest.mark.asyncio
    async def test_corrupted_json_raises_state_corrupted(self, tmp_path: Path) -> None:
        """Loading a file with invalid JSON raises StateError(STATE_CORRUPTED)."""
        state_dir = tmp_path / "state"
        state_dir.mkdir()
        (state_dir / "wf-bad.json").write_text("NOT-VALID-JSON{{{")

        store = JSONFileStateStore(state_dir)

        with pytest.raises(StateError) as exc_info:
            await store.load("wf-bad")
        assert exc_info.value.code == STATE_CORRUPTED

    @pytest.mark.asyncio
    async def test_save_error_raises_state_save_failed(self, tmp_path: Path) -> None:
        """Write error raises StateError(STATE_SAVE_FAILED)."""
        store = JSONFileStateStore(tmp_path / "state")

        with patch(
            "beddel.adapters.state_store.tempfile.mkstemp",
            side_effect=PermissionError("denied"),
        ):
            with pytest.raises(StateError) as exc_info:
                await store.save("wf-1", {"data": "test"})
            assert exc_info.value.code == STATE_SAVE_FAILED

    @pytest.mark.asyncio
    async def test_load_error_raises_state_load_failed(self, tmp_path: Path) -> None:
        """Read error raises StateError(STATE_LOAD_FAILED)."""
        state_dir = tmp_path / "state"
        state_dir.mkdir()
        target = state_dir / "wf-err.json"
        target.write_text('{"ok": true}')
        target.chmod(0o000)

        store = JSONFileStateStore(state_dir)

        try:
            with pytest.raises(StateError) as exc_info:
                await store.load("wf-err")
            assert exc_info.value.code == STATE_LOAD_FAILED
        finally:
            target.chmod(0o644)

    @pytest.mark.asyncio
    async def test_delete_error_raises_state_delete_failed(self, tmp_path: Path) -> None:
        """Delete error raises StateError(STATE_DELETE_FAILED)."""
        store = JSONFileStateStore(tmp_path / "state")

        with patch(
            "pathlib.Path.unlink",
            side_effect=PermissionError("denied"),
        ):
            with pytest.raises(StateError) as exc_info:
                await store.delete("wf-1")
            assert exc_info.value.code == STATE_DELETE_FAILED

    @pytest.mark.asyncio
    async def test_atomic_write_creates_json_file(self, tmp_path: Path) -> None:
        """Verify the final file is valid JSON after atomic write."""
        store = JSONFileStateStore(tmp_path / "state")
        state = {"complex": {"nested": [1, 2, 3]}, "flag": True}

        await store.save("wf-atomic", state)

        target = tmp_path / "state" / "wf-atomic.json"
        assert target.exists()
        with open(target) as f:
            on_disk = json.load(f)
        assert on_disk == state

    @pytest.mark.asyncio
    async def test_no_temp_files_left_on_success(self, tmp_path: Path) -> None:
        """After successful save, no .tmp files remain in directory."""
        state_dir = tmp_path / "state"
        store = JSONFileStateStore(state_dir)

        await store.save("wf-1", {"data": "ok"})

        tmp_files = list(state_dir.glob("*.tmp"))
        assert tmp_files == []

    @pytest.mark.asyncio
    async def test_persistence_across_instances(self, tmp_path: Path) -> None:
        """Save with one instance, load with a new instance."""
        state_dir = tmp_path / "state"

        store1 = JSONFileStateStore(state_dir)
        await store1.save("wf-1", {"result": "ok"})

        store2 = JSONFileStateStore(state_dir)
        loaded = await store2.load("wf-1")

        assert loaded == {"result": "ok"}

    @pytest.mark.asyncio
    async def test_multiple_workflows_isolated(self, tmp_path: Path) -> None:
        """States for different workflow_ids are independent."""
        store = JSONFileStateStore(tmp_path / "state")

        await store.save("wf-1", {"data": "one"})
        await store.save("wf-2", {"data": "two"})

        assert (await store.load("wf-1")) == {"data": "one"}
        assert (await store.load("wf-2")) == {"data": "two"}

        await store.delete("wf-1")
        assert await store.load("wf-1") is None
        assert (await store.load("wf-2")) == {"data": "two"}

    @pytest.mark.asyncio
    async def test_path_traversal_rejected(self, tmp_path: Path) -> None:
        """Workflow IDs with path traversal characters are rejected."""
        store = JSONFileStateStore(tmp_path / "state")

        for bad_id in ["../etc/passwd", "foo/bar", "a\x00b", "foo\\bar"]:
            with pytest.raises((ValueError, StateError)):
                await store.save(bad_id, {"data": "evil"})

    @pytest.mark.asyncio
    async def test_concurrent_writes_no_corruption(self, tmp_path: Path) -> None:
        """Two concurrent saves to the same workflow_id don't corrupt."""
        import asyncio

        store = JSONFileStateStore(tmp_path / "state")

        async def write(value: int) -> None:
            await store.save("wf-race", {"value": value})

        await asyncio.gather(write(1), write(2))

        loaded = await store.load("wf-race")
        assert loaded is not None
        assert loaded["value"] in (1, 2)
        # Verify it's valid JSON on disk
        with open(tmp_path / "state" / "wf-race.json") as f:
            on_disk = json.load(f)
        assert on_disk["value"] in (1, 2)

    @pytest.mark.asyncio
    async def test_string_directory_accepted(self, tmp_path: Path) -> None:
        """Constructor accepts string path as well as Path."""
        store = JSONFileStateStore(str(tmp_path / "str-state"))

        await store.save("wf-1", {"ok": True})
        loaded = await store.load("wf-1")

        assert loaded == {"ok": True}

    @pytest.mark.asyncio
    async def test_empty_workflow_id_rejected(self, tmp_path: Path) -> None:
        """Empty workflow_id is rejected."""
        store = JSONFileStateStore(tmp_path / "state")

        with pytest.raises((ValueError, StateError)):
            await store.save("", {"data": "bad"})
