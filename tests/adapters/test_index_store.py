"""Tests for IndexStore adapter (schema init, WAL mode, auto-creation)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

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
