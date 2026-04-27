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
