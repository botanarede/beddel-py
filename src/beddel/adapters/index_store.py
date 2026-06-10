"""Index store adapter for kit/flow discovery persistence.

Provides :class:`IndexStore` — a persistent SQLite-backed store for
kit and flow index data, enabling enable/disable filtering and
user preferences.

Follows the same patterns as :class:`~beddel.adapters.event_store.SQLiteEventStore`:
short-lived connections, WAL journal mode, ``asyncio.to_thread()`` for
non-blocking I/O, and lazy schema initialization.
"""

from __future__ import annotations

import asyncio
import contextlib
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from beddel.domain.kit import KitManifest
    from beddel.domain.models import Workflow

_DEFAULT_DB_PATH = Path("~/.config/beddel/index.db")


class IndexStore:
    """Persistent SQLite-backed index store for kits, flows, and user prefs.

    Stores discovery metadata for kits and flows with enable/disable
    state, plus arbitrary user preferences.  Uses WAL journal mode and
    short-lived connections for concurrent read performance.

    Args:
        db_path: Path to the SQLite database file.  Defaults to
            ``~/.config/beddel/index.db``.  Parent directories are
            created automatically if they don't exist.
    """

    def __init__(self, db_path: str | Path = _DEFAULT_DB_PATH) -> None:
        self._db_path = str(Path(db_path).expanduser())
        self._initialized = False

    def _connect(self) -> sqlite3.Connection:
        """Open a short-lived connection with WAL mode enabled."""
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_schema(self) -> None:
        """Create tables and indexes if they don't exist."""
        conn = self._connect()
        with conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS kit_index ("
                "name TEXT PRIMARY KEY, "
                "version TEXT NOT NULL, "
                "description TEXT NOT NULL DEFAULT '', "
                "category TEXT NOT NULL DEFAULT 'general', "
                "path TEXT NOT NULL, "
                "enabled INTEGER NOT NULL DEFAULT 1, "
                "port TEXT NOT NULL DEFAULT '', "
                "discovered_at TEXT NOT NULL, "
                "updated_at TEXT NOT NULL"
                ")"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS flow_index ("
                "id TEXT PRIMARY KEY, "
                "name TEXT NOT NULL, "
                "description TEXT NOT NULL DEFAULT '', "
                "category TEXT NOT NULL DEFAULT 'general', "
                "path TEXT NOT NULL, "
                "enabled INTEGER NOT NULL DEFAULT 1, "
                "step_count INTEGER NOT NULL DEFAULT 0, "
                "discovered_at TEXT NOT NULL, "
                "updated_at TEXT NOT NULL"
                ")"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS user_prefs ("
                "key TEXT PRIMARY KEY, "
                "value TEXT NOT NULL, "
                "updated_at TEXT NOT NULL DEFAULT ''"
                ")"
            )
            # Migration: add updated_at to legacy user_prefs tables (pre-v0.1.8)
            with contextlib.suppress(sqlite3.OperationalError):
                conn.execute(
                    "ALTER TABLE user_prefs ADD COLUMN updated_at TEXT NOT NULL DEFAULT ''"
                )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_kit_enabled ON kit_index (enabled)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_flow_enabled ON flow_index (enabled)")
        conn.close()

    async def _ensure_initialized(self) -> None:
        """Initialize the database schema on first use."""
        if not self._initialized:
            await asyncio.to_thread(self._init_schema)
            self._initialized = True

    async def sync_kits(self, manifests: list[KitManifest]) -> None:
        """Upsert kit_index rows from discovered manifests.

        New kits are inserted with ``enabled=1``.  Existing kits preserve
        their current ``enabled`` value.  Kits no longer present in
        *manifests* are deleted (stale entry cleanup).

        Args:
            manifests: List of validated kit manifests from discovery.
        """
        await self._ensure_initialized()

        def _sync() -> None:
            conn = self._connect()
            with conn:
                # Read existing state to preserve enabled + discovered_at
                cursor = conn.execute("SELECT name, enabled, discovered_at FROM kit_index")
                existing: dict[str, tuple[int, str]] = {
                    row[0]: (row[1], row[2]) for row in cursor.fetchall()
                }

                now = datetime.now(tz=UTC).isoformat()
                manifest_names: list[str] = []

                for manifest in manifests:
                    name = manifest.kit.name
                    manifest_names.append(name)
                    category = (
                        manifest.kit.adapters[0].port if manifest.kit.adapters else "general"
                    )
                    port = manifest.kit.adapters[0].port if manifest.kit.adapters else ""
                    if name in existing:
                        enabled = existing[name][0]
                        discovered_at = existing[name][1]
                    else:
                        enabled = 1
                        discovered_at = now

                    conn.execute(
                        "INSERT OR REPLACE INTO kit_index "
                        "(name, version, description, category, path, "
                        "enabled, port, discovered_at, updated_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            name,
                            manifest.kit.version,
                            manifest.kit.description,
                            category,
                            str(manifest.root_path),
                            enabled,
                            port,
                            discovered_at,
                            now,
                        ),
                    )

                # Remove stale entries
                if manifest_names:
                    placeholders = ",".join("?" * len(manifest_names))
                    conn.execute(
                        f"DELETE FROM kit_index WHERE name NOT IN ({placeholders})",
                        manifest_names,
                    )
                else:
                    conn.execute("DELETE FROM kit_index")
            conn.close()

        await asyncio.to_thread(_sync)

    async def list_kits(self, *, enabled_only: bool = False) -> list[dict[str, Any]]:
        """Return all rows from kit_index as dicts.

        Args:
            enabled_only: If ``True``, filter to rows where ``enabled = 1``.

        Returns:
            List of kit index rows as dictionaries.
        """
        await self._ensure_initialized()

        def _read() -> list[dict[str, Any]]:
            conn = self._connect()
            conn.row_factory = sqlite3.Row
            query = "SELECT * FROM kit_index"
            if enabled_only:
                query += " WHERE enabled = 1"
            rows = conn.execute(query).fetchall()
            conn.close()
            return [dict(row) for row in rows]

        return await asyncio.to_thread(_read)

    async def set_kit_enabled(self, name: str, enabled: bool) -> bool:
        """Toggle the enabled state of a kit.

        Args:
            name: Kit name (primary key in kit_index).
            enabled: New enabled state.

        Returns:
            ``True`` if the row was updated, ``False`` if kit not found.
        """
        await self._ensure_initialized()

        def _update() -> bool:
            conn = self._connect()
            with conn:
                cursor = conn.execute(
                    "UPDATE kit_index SET enabled = ? WHERE name = ?",
                    (int(enabled), name),
                )
            result = cursor.rowcount > 0
            conn.close()
            return result

        return await asyncio.to_thread(_update)

    async def sync_flows(self, workflows: list[tuple[Workflow, Path]]) -> None:
        """Upsert flow_index rows from discovered workflows.

        New flows are inserted with ``enabled=1``.  Existing flows preserve
        their current ``enabled`` value.  Flows no longer present in
        *workflows* are deleted (stale entry cleanup).

        Args:
            workflows: List of (Workflow, yaml_file_path) tuples from discovery.
        """
        await self._ensure_initialized()

        def _sync() -> None:
            conn = self._connect()
            with conn:
                # Read existing state to preserve enabled + discovered_at
                cursor = conn.execute("SELECT id, enabled, discovered_at FROM flow_index")
                existing: dict[str, tuple[int, str]] = {
                    row[0]: (row[1], row[2]) for row in cursor.fetchall()
                }

                now = datetime.now(tz=UTC).isoformat()
                workflow_ids: list[str] = []

                for workflow, path in workflows:
                    wf_id = workflow.id
                    workflow_ids.append(wf_id)
                    category = workflow.metadata.get("category", "general")
                    step_count = len(workflow.steps)

                    if wf_id in existing:
                        enabled = existing[wf_id][0]
                        discovered_at = existing[wf_id][1]
                    else:
                        enabled = 1
                        discovered_at = now

                    conn.execute(
                        "INSERT OR REPLACE INTO flow_index "
                        "(id, name, description, category, path, "
                        "enabled, step_count, discovered_at, updated_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            wf_id,
                            workflow.name,
                            workflow.description,
                            category,
                            str(path),
                            enabled,
                            step_count,
                            discovered_at,
                            now,
                        ),
                    )

                # Remove stale entries
                if workflow_ids:
                    placeholders = ",".join("?" * len(workflow_ids))
                    conn.execute(
                        f"DELETE FROM flow_index WHERE id NOT IN ({placeholders})",
                        workflow_ids,
                    )
                else:
                    conn.execute("DELETE FROM flow_index")
            conn.close()

        await asyncio.to_thread(_sync)

    async def list_flows(self, *, enabled_only: bool = False) -> list[dict[str, Any]]:
        """Return all rows from flow_index as dicts.

        Args:
            enabled_only: If ``True``, filter to rows where ``enabled = 1``.

        Returns:
            List of flow index rows as dictionaries.
        """
        await self._ensure_initialized()

        def _read() -> list[dict[str, Any]]:
            conn = self._connect()
            conn.row_factory = sqlite3.Row
            query = "SELECT * FROM flow_index"
            if enabled_only:
                query += " WHERE enabled = 1"
            rows = conn.execute(query).fetchall()
            conn.close()
            return [dict(row) for row in rows]

        return await asyncio.to_thread(_read)

    async def set_flow_enabled(self, flow_id: str, enabled: bool) -> bool:
        """Toggle the enabled state of a flow.

        Args:
            flow_id: Flow ID (primary key in flow_index).
            enabled: New enabled state.

        Returns:
            ``True`` if the row was updated, ``False`` if flow not found.
        """
        await self._ensure_initialized()

        def _update() -> bool:
            conn = self._connect()
            with conn:
                cursor = conn.execute(
                    "UPDATE flow_index SET enabled = ? WHERE id = ?",
                    (int(enabled), flow_id),
                )
            result = cursor.rowcount > 0
            conn.close()
            return result

        return await asyncio.to_thread(_update)

    async def get_pref(self, key: str) -> str | None:
        """Read a user preference by key.

        Args:
            key: Preference key (primary key in user_prefs).

        Returns:
            The stored value, or ``None`` if the key does not exist.
        """
        await self._ensure_initialized()

        def _read() -> str | None:
            conn = self._connect()
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT value FROM user_prefs WHERE key = ?", (key,)).fetchone()
            conn.close()
            return row["value"] if row else None

        return await asyncio.to_thread(_read)

    async def set_pref(self, key: str, value: str) -> None:
        """Write a user preference (insert or overwrite).

        Args:
            key: Preference key (primary key in user_prefs).
            value: Preference value to store.
        """
        await self._ensure_initialized()

        def _write() -> None:
            conn = self._connect()
            now = datetime.now(tz=UTC).isoformat()
            with conn:
                conn.execute(
                    "INSERT OR REPLACE INTO user_prefs (key, value, updated_at) VALUES (?, ?, ?)",
                    (key, value, now),
                )
            conn.close()

        await asyncio.to_thread(_write)
