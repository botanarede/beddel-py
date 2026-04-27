"""Tests for IndexStore adapter (schema init, WAL mode, auto-creation)."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass as _dataclass
from datetime import UTC as _UTC
from datetime import datetime as _datetime
from pathlib import Path

import pytest
from pydantic import BaseModel as _BaseModel

from beddel.adapters.index_store import IndexStore


class TestIndexStoreSchemaCreation:
    """Verify schema tables and indexes are created after initialization."""

    @pytest.mark.asyncio
    async def test_tables_exist_after_init(self, tmp_path: Path) -> None:
        """All 3 tables (kit_index, flow_index, user_prefs) exist after init."""
        store = IndexStore(tmp_path / "index.db")
        await store._ensure_initialized()

        conn = sqlite3.connect(str(tmp_path / "index.db"))
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = [row[0] for row in cursor.fetchall()]
        conn.close()

        assert "kit_index" in tables
        assert "flow_index" in tables
        assert "user_prefs" in tables

    @pytest.mark.asyncio
    async def test_indexes_exist_after_init(self, tmp_path: Path) -> None:
        """Both indexes (idx_kit_enabled, idx_flow_enabled) exist after init."""
        store = IndexStore(tmp_path / "index.db")
        await store._ensure_initialized()

        conn = sqlite3.connect(str(tmp_path / "index.db"))
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='index' ORDER BY name")
        indexes = [row[0] for row in cursor.fetchall()]
        conn.close()

        assert "idx_kit_enabled" in indexes
        assert "idx_flow_enabled" in indexes

    @pytest.mark.asyncio
    async def test_kit_index_columns(self, tmp_path: Path) -> None:
        """kit_index table has the expected columns."""
        store = IndexStore(tmp_path / "index.db")
        await store._ensure_initialized()

        conn = sqlite3.connect(str(tmp_path / "index.db"))
        cursor = conn.execute("PRAGMA table_info(kit_index)")
        columns = {row[1] for row in cursor.fetchall()}
        conn.close()

        expected = {
            "name",
            "version",
            "description",
            "category",
            "path",
            "enabled",
            "port",
            "discovered_at",
            "updated_at",
        }
        assert columns == expected

    @pytest.mark.asyncio
    async def test_flow_index_columns(self, tmp_path: Path) -> None:
        """flow_index table has the expected columns."""
        store = IndexStore(tmp_path / "index.db")
        await store._ensure_initialized()

        conn = sqlite3.connect(str(tmp_path / "index.db"))
        cursor = conn.execute("PRAGMA table_info(flow_index)")
        columns = {row[1] for row in cursor.fetchall()}
        conn.close()

        expected = {
            "id",
            "name",
            "description",
            "category",
            "path",
            "enabled",
            "step_count",
            "discovered_at",
            "updated_at",
        }
        assert columns == expected

    @pytest.mark.asyncio
    async def test_user_prefs_columns(self, tmp_path: Path) -> None:
        """user_prefs table has the expected columns."""
        store = IndexStore(tmp_path / "index.db")
        await store._ensure_initialized()

        conn = sqlite3.connect(str(tmp_path / "index.db"))
        cursor = conn.execute("PRAGMA table_info(user_prefs)")
        columns = {row[1] for row in cursor.fetchall()}
        conn.close()

        expected = {"key", "value", "updated_at"}
        assert columns == expected


class TestIndexStoreConnect:
    """Verify _connect() returns WAL mode connection."""

    @pytest.mark.asyncio
    async def test_connect_returns_wal_mode(self, tmp_path: Path) -> None:
        """_connect() sets journal_mode to WAL."""
        store = IndexStore(tmp_path / "index.db")
        conn = store._connect()

        result = conn.execute("PRAGMA journal_mode").fetchone()
        conn.close()

        assert result is not None
        assert result[0] == "wal"

    @pytest.mark.asyncio
    async def test_connect_returns_connection(self, tmp_path: Path) -> None:
        """_connect() returns a sqlite3.Connection instance."""
        store = IndexStore(tmp_path / "index.db")
        conn = store._connect()

        assert isinstance(conn, sqlite3.Connection)
        conn.close()


class TestIndexStoreAutoCreation:
    """Verify db file is auto-created in the specified directory."""

    @pytest.mark.asyncio
    async def test_auto_creates_db_file(self, tmp_path: Path) -> None:
        """Database file is created on first _ensure_initialized()."""
        db_path = tmp_path / "index.db"
        assert not db_path.exists()

        store = IndexStore(db_path)
        await store._ensure_initialized()

        assert db_path.exists()

    @pytest.mark.asyncio
    async def test_auto_creates_parent_directories(self, tmp_path: Path) -> None:
        """Parent directories are created if they don't exist."""
        db_path = tmp_path / "nested" / "dir" / "index.db"
        assert not db_path.parent.exists()

        store = IndexStore(db_path)
        await store._ensure_initialized()

        assert db_path.exists()

    @pytest.mark.asyncio
    async def test_idempotent_initialization(self, tmp_path: Path) -> None:
        """Calling _ensure_initialized() multiple times is safe."""
        store = IndexStore(tmp_path / "index.db")

        await store._ensure_initialized()
        await store._ensure_initialized()

        # Should not raise — schema already exists
        conn = sqlite3.connect(str(tmp_path / "index.db"))
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = [row[0] for row in cursor.fetchall()]
        conn.close()

        assert "kit_index" in tables


# --- Task 2 tests: sync_kits, list_kits, set_kit_enabled ---


# Lightweight test helpers to avoid importing full domain models
class _FakeAdapterDecl(_BaseModel):
    port: str


class _FakeSolutionKit(_BaseModel):
    name: str
    version: str
    description: str = ""
    adapters: list[_FakeAdapterDecl] = []


@_dataclass(frozen=True)
class _FakeKitManifest:
    kit: _FakeSolutionKit
    root_path: Path
    loaded_at: _datetime
    source: str = "local"


def _make_manifest(
    name: str,
    version: str = "1.0.0",
    description: str = "",
    port: str | None = None,
    root_path: Path | None = None,
) -> _FakeKitManifest:
    adapters = [_FakeAdapterDecl(port=port)] if port else []
    kit = _FakeSolutionKit(name=name, version=version, description=description, adapters=adapters)
    return _FakeKitManifest(
        kit=kit,
        root_path=root_path or Path("/kits") / name,
        loaded_at=_datetime.now(tz=_UTC),
    )


class TestSyncKitsInsert:
    """sync_kits inserts new kits with enabled=1."""

    @pytest.mark.asyncio
    async def test_inserts_new_kit_with_enabled_1(self, tmp_path: Path) -> None:
        store = IndexStore(tmp_path / "index.db")
        manifests = [_make_manifest("my-kit", version="0.2.0", description="A kit")]

        await store.sync_kits(manifests)  # type: ignore[arg-type]

        rows = await store.list_kits()
        assert len(rows) == 1
        assert rows[0]["name"] == "my-kit"
        assert rows[0]["version"] == "0.2.0"
        assert rows[0]["description"] == "A kit"
        assert rows[0]["enabled"] == 1

    @pytest.mark.asyncio
    async def test_inserts_category_from_adapter_port(self, tmp_path: Path) -> None:
        store = IndexStore(tmp_path / "index.db")
        manifests = [_make_manifest("llm-kit", port="ILLMProvider")]

        await store.sync_kits(manifests)  # type: ignore[arg-type]

        rows = await store.list_kits()
        assert rows[0]["category"] == "ILLMProvider"
        assert rows[0]["port"] == "ILLMProvider"

    @pytest.mark.asyncio
    async def test_inserts_general_category_without_adapters(self, tmp_path: Path) -> None:
        store = IndexStore(tmp_path / "index.db")
        manifests = [_make_manifest("plain-kit")]

        await store.sync_kits(manifests)  # type: ignore[arg-type]

        rows = await store.list_kits()
        assert rows[0]["category"] == "general"
        assert rows[0]["port"] == ""


class TestSyncKitsUpdate:
    """sync_kits updates existing kit version/path."""

    @pytest.mark.asyncio
    async def test_updates_version_and_path(self, tmp_path: Path) -> None:
        store = IndexStore(tmp_path / "index.db")
        m1 = [_make_manifest("my-kit", version="1.0.0", root_path=Path("/old/path"))]
        await store.sync_kits(m1)  # type: ignore[arg-type]

        m2 = [_make_manifest("my-kit", version="2.0.0", root_path=Path("/new/path"))]
        await store.sync_kits(m2)  # type: ignore[arg-type]

        rows = await store.list_kits()
        assert len(rows) == 1
        assert rows[0]["version"] == "2.0.0"
        assert rows[0]["path"] == "/new/path"


class TestSyncKitsDelete:
    """sync_kits deletes removed kits."""

    @pytest.mark.asyncio
    async def test_deletes_stale_kits(self, tmp_path: Path) -> None:
        store = IndexStore(tmp_path / "index.db")
        m1 = [_make_manifest("kit-a"), _make_manifest("kit-b")]
        await store.sync_kits(m1)  # type: ignore[arg-type]

        # Second sync only has kit-a
        m2 = [_make_manifest("kit-a")]
        await store.sync_kits(m2)  # type: ignore[arg-type]

        rows = await store.list_kits()
        assert len(rows) == 1
        assert rows[0]["name"] == "kit-a"

    @pytest.mark.asyncio
    async def test_deletes_all_when_empty_manifests(self, tmp_path: Path) -> None:
        store = IndexStore(tmp_path / "index.db")
        m1 = [_make_manifest("kit-a")]
        await store.sync_kits(m1)  # type: ignore[arg-type]

        await store.sync_kits([])  # type: ignore[arg-type]

        rows = await store.list_kits()
        assert len(rows) == 0


class TestSyncKitsPreservesEnabled:
    """sync_kits preserves enabled=0 for existing disabled kits."""

    @pytest.mark.asyncio
    async def test_preserves_disabled_state(self, tmp_path: Path) -> None:
        store = IndexStore(tmp_path / "index.db")
        m1 = [_make_manifest("my-kit")]
        await store.sync_kits(m1)  # type: ignore[arg-type]

        # Disable the kit
        await store.set_kit_enabled("my-kit", enabled=False)

        # Re-sync — should preserve enabled=0
        m2 = [_make_manifest("my-kit", version="2.0.0")]
        await store.sync_kits(m2)  # type: ignore[arg-type]

        rows = await store.list_kits()
        assert rows[0]["enabled"] == 0
        assert rows[0]["version"] == "2.0.0"


class TestListKits:
    """list_kits returns all rows or filters by enabled."""

    @pytest.mark.asyncio
    async def test_returns_all_kits(self, tmp_path: Path) -> None:
        store = IndexStore(tmp_path / "index.db")
        m = [_make_manifest("kit-a"), _make_manifest("kit-b")]
        await store.sync_kits(m)  # type: ignore[arg-type]

        rows = await store.list_kits()
        names = {r["name"] for r in rows}
        assert names == {"kit-a", "kit-b"}

    @pytest.mark.asyncio
    async def test_enabled_only_filters(self, tmp_path: Path) -> None:
        store = IndexStore(tmp_path / "index.db")
        m = [_make_manifest("kit-a"), _make_manifest("kit-b")]
        await store.sync_kits(m)  # type: ignore[arg-type]
        await store.set_kit_enabled("kit-b", enabled=False)

        rows = await store.list_kits(enabled_only=True)
        assert len(rows) == 1
        assert rows[0]["name"] == "kit-a"

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_kits(self, tmp_path: Path) -> None:
        store = IndexStore(tmp_path / "index.db")
        await store._ensure_initialized()

        rows = await store.list_kits()
        assert rows == []


class TestSetKitEnabled:
    """set_kit_enabled toggles and returns True/False."""

    @pytest.mark.asyncio
    async def test_returns_true_on_existing_kit(self, tmp_path: Path) -> None:
        store = IndexStore(tmp_path / "index.db")
        m = [_make_manifest("my-kit")]
        await store.sync_kits(m)  # type: ignore[arg-type]

        result = await store.set_kit_enabled("my-kit", enabled=False)
        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_on_missing_kit(self, tmp_path: Path) -> None:
        store = IndexStore(tmp_path / "index.db")
        await store._ensure_initialized()

        result = await store.set_kit_enabled("nonexistent", enabled=True)
        assert result is False

    @pytest.mark.asyncio
    async def test_toggles_enabled_state(self, tmp_path: Path) -> None:
        store = IndexStore(tmp_path / "index.db")
        m = [_make_manifest("my-kit")]
        await store.sync_kits(m)  # type: ignore[arg-type]

        await store.set_kit_enabled("my-kit", enabled=False)
        rows = await store.list_kits()
        assert rows[0]["enabled"] == 0

        await store.set_kit_enabled("my-kit", enabled=True)
        rows = await store.list_kits()
        assert rows[0]["enabled"] == 1


# --- Task 3 tests: sync_flows, list_flows, set_flow_enabled ---


class _FakeStep(_BaseModel):
    id: str
    name: str
    primitive: str
    config: dict[str, str] = {}


class _FakeWorkflow(_BaseModel):
    id: str
    name: str
    description: str = ""
    version: str = "1.0"
    steps: list[_FakeStep] = []
    metadata: dict[str, str] = {}


def _make_workflow(
    wf_id: str,
    name: str,
    *,
    steps: int = 2,
    category: str | None = None,
    path: Path | None = None,
) -> tuple[_FakeWorkflow, Path]:
    step_list = [
        _FakeStep(id=f"step-{i}", name=f"Step {i}", primitive="llm") for i in range(steps)
    ]
    metadata: dict[str, str] = {}
    if category is not None:
        metadata["category"] = category
    wf = _FakeWorkflow(id=wf_id, name=name, steps=step_list, metadata=metadata)
    wf_path = path or Path(f"/flows/{wf_id}.yaml")
    return wf, wf_path


class TestSyncFlowsInsert:
    """sync_flows inserts new flows with enabled=1."""

    @pytest.mark.asyncio
    async def test_inserts_new_flow_with_enabled_1(self, tmp_path: Path) -> None:
        store = IndexStore(tmp_path / "index.db")
        workflows = [_make_workflow("flow-1", "My Flow")]

        await store.sync_flows(workflows)  # type: ignore[arg-type]

        rows = await store.list_flows()
        assert len(rows) == 1
        assert rows[0]["id"] == "flow-1"
        assert rows[0]["name"] == "My Flow"
        assert rows[0]["enabled"] == 1
        assert rows[0]["step_count"] == 2

    @pytest.mark.asyncio
    async def test_inserts_category_from_metadata(self, tmp_path: Path) -> None:
        store = IndexStore(tmp_path / "index.db")
        workflows = [_make_workflow("flow-1", "Deploy Flow", category="deployment")]

        await store.sync_flows(workflows)  # type: ignore[arg-type]

        rows = await store.list_flows()
        assert rows[0]["category"] == "deployment"

    @pytest.mark.asyncio
    async def test_inserts_general_category_without_metadata(self, tmp_path: Path) -> None:
        store = IndexStore(tmp_path / "index.db")
        workflows = [_make_workflow("flow-1", "Plain Flow")]

        await store.sync_flows(workflows)  # type: ignore[arg-type]

        rows = await store.list_flows()
        assert rows[0]["category"] == "general"

    @pytest.mark.asyncio
    async def test_inserts_path_from_tuple(self, tmp_path: Path) -> None:
        store = IndexStore(tmp_path / "index.db")
        workflows = [_make_workflow("flow-1", "My Flow", path=Path("/custom/path.yaml"))]

        await store.sync_flows(workflows)  # type: ignore[arg-type]

        rows = await store.list_flows()
        assert rows[0]["path"] == "/custom/path.yaml"


class TestSyncFlowsUpdate:
    """sync_flows updates existing flow fields."""

    @pytest.mark.asyncio
    async def test_updates_name_and_path(self, tmp_path: Path) -> None:
        store = IndexStore(tmp_path / "index.db")
        w1 = [_make_workflow("flow-1", "Old Name", path=Path("/old/path.yaml"))]
        await store.sync_flows(w1)  # type: ignore[arg-type]

        w2 = [_make_workflow("flow-1", "New Name", path=Path("/new/path.yaml"))]
        await store.sync_flows(w2)  # type: ignore[arg-type]

        rows = await store.list_flows()
        assert len(rows) == 1
        assert rows[0]["name"] == "New Name"
        assert rows[0]["path"] == "/new/path.yaml"

    @pytest.mark.asyncio
    async def test_updates_step_count(self, tmp_path: Path) -> None:
        store = IndexStore(tmp_path / "index.db")
        w1 = [_make_workflow("flow-1", "Flow", steps=2)]
        await store.sync_flows(w1)  # type: ignore[arg-type]

        w2 = [_make_workflow("flow-1", "Flow", steps=5)]
        await store.sync_flows(w2)  # type: ignore[arg-type]

        rows = await store.list_flows()
        assert rows[0]["step_count"] == 5


class TestSyncFlowsDelete:
    """sync_flows deletes removed flows."""

    @pytest.mark.asyncio
    async def test_deletes_stale_flows(self, tmp_path: Path) -> None:
        store = IndexStore(tmp_path / "index.db")
        w1 = [_make_workflow("flow-a", "A"), _make_workflow("flow-b", "B")]
        await store.sync_flows(w1)  # type: ignore[arg-type]

        # Second sync only has flow-a
        w2 = [_make_workflow("flow-a", "A")]
        await store.sync_flows(w2)  # type: ignore[arg-type]

        rows = await store.list_flows()
        assert len(rows) == 1
        assert rows[0]["id"] == "flow-a"

    @pytest.mark.asyncio
    async def test_deletes_all_when_empty_workflows(self, tmp_path: Path) -> None:
        store = IndexStore(tmp_path / "index.db")
        w1 = [_make_workflow("flow-a", "A")]
        await store.sync_flows(w1)  # type: ignore[arg-type]

        await store.sync_flows([])  # type: ignore[arg-type]

        rows = await store.list_flows()
        assert len(rows) == 0


class TestSyncFlowsPreservesEnabled:
    """sync_flows preserves enabled=0 for existing disabled flows."""

    @pytest.mark.asyncio
    async def test_preserves_disabled_state(self, tmp_path: Path) -> None:
        store = IndexStore(tmp_path / "index.db")
        w1 = [_make_workflow("flow-1", "Flow")]
        await store.sync_flows(w1)  # type: ignore[arg-type]

        # Disable the flow
        await store.set_flow_enabled("flow-1", enabled=False)

        # Re-sync — should preserve enabled=0
        w2 = [_make_workflow("flow-1", "Flow Updated", steps=4)]
        await store.sync_flows(w2)  # type: ignore[arg-type]

        rows = await store.list_flows()
        assert rows[0]["enabled"] == 0
        assert rows[0]["name"] == "Flow Updated"
        assert rows[0]["step_count"] == 4


class TestListFlows:
    """list_flows returns all rows or filters by enabled."""

    @pytest.mark.asyncio
    async def test_returns_all_flows(self, tmp_path: Path) -> None:
        store = IndexStore(tmp_path / "index.db")
        w = [_make_workflow("flow-a", "A"), _make_workflow("flow-b", "B")]
        await store.sync_flows(w)  # type: ignore[arg-type]

        rows = await store.list_flows()
        ids = {r["id"] for r in rows}
        assert ids == {"flow-a", "flow-b"}

    @pytest.mark.asyncio
    async def test_enabled_only_filters(self, tmp_path: Path) -> None:
        store = IndexStore(tmp_path / "index.db")
        w = [_make_workflow("flow-a", "A"), _make_workflow("flow-b", "B")]
        await store.sync_flows(w)  # type: ignore[arg-type]
        await store.set_flow_enabled("flow-b", enabled=False)

        rows = await store.list_flows(enabled_only=True)
        assert len(rows) == 1
        assert rows[0]["id"] == "flow-a"

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_flows(self, tmp_path: Path) -> None:
        store = IndexStore(tmp_path / "index.db")
        await store._ensure_initialized()

        rows = await store.list_flows()
        assert rows == []


class TestSetFlowEnabled:
    """set_flow_enabled toggles and returns True/False."""

    @pytest.mark.asyncio
    async def test_returns_true_on_existing_flow(self, tmp_path: Path) -> None:
        store = IndexStore(tmp_path / "index.db")
        w = [_make_workflow("flow-1", "Flow")]
        await store.sync_flows(w)  # type: ignore[arg-type]

        result = await store.set_flow_enabled("flow-1", enabled=False)
        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_on_missing_flow(self, tmp_path: Path) -> None:
        store = IndexStore(tmp_path / "index.db")
        await store._ensure_initialized()

        result = await store.set_flow_enabled("nonexistent", enabled=True)
        assert result is False

    @pytest.mark.asyncio
    async def test_toggles_enabled_state(self, tmp_path: Path) -> None:
        store = IndexStore(tmp_path / "index.db")
        w = [_make_workflow("flow-1", "Flow")]
        await store.sync_flows(w)  # type: ignore[arg-type]

        await store.set_flow_enabled("flow-1", enabled=False)
        rows = await store.list_flows()
        assert rows[0]["enabled"] == 0

        await store.set_flow_enabled("flow-1", enabled=True)
        rows = await store.list_flows()
        assert rows[0]["enabled"] == 1


# --- Task 1 (Story BC8.4) tests: get_pref, set_pref ---


class TestGetPref:
    """get_pref returns value or None."""

    @pytest.mark.asyncio
    async def test_returns_none_for_missing_key(self, tmp_path: Path) -> None:
        """get_pref returns None when key does not exist."""
        store = IndexStore(tmp_path / "index.db")

        result = await store.get_pref("nonexistent_key")

        assert result is None

    @pytest.mark.asyncio
    async def test_roundtrip_set_then_get(self, tmp_path: Path) -> None:
        """set_pref + get_pref roundtrip returns the stored value."""
        store = IndexStore(tmp_path / "index.db")

        await store.set_pref("llm_provider", "gemini")
        result = await store.get_pref("llm_provider")

        assert result == "gemini"


class TestSetPref:
    """set_pref inserts and overwrites preferences."""

    @pytest.mark.asyncio
    async def test_overwrites_existing_value(self, tmp_path: Path) -> None:
        """set_pref overwrites an existing key with a new value."""
        store = IndexStore(tmp_path / "index.db")

        await store.set_pref("llm_provider", "gemini")
        await store.set_pref("llm_provider", "openai")
        result = await store.get_pref("llm_provider")

        assert result == "openai"

    @pytest.mark.asyncio
    async def test_updated_at_is_set(self, tmp_path: Path) -> None:
        """set_pref stores an ISO timestamp in updated_at."""
        store = IndexStore(tmp_path / "index.db")

        await store.set_pref("theme", "dark")

        # Verify directly in the database
        conn = sqlite3.connect(str(tmp_path / "index.db"))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT updated_at FROM user_prefs WHERE key = ?", ("theme",)
        ).fetchone()
        conn.close()

        assert row is not None
        # Verify it's a valid ISO timestamp
        parsed = _datetime.fromisoformat(row["updated_at"])
        assert parsed.tzinfo is not None
