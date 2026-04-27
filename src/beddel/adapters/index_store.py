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
import sqlite3
from pathlib import Path

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
                "updated_at TEXT NOT NULL"
                ")"
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_kit_enabled ON kit_index (enabled)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_flow_enabled ON flow_index (enabled)")
        conn.close()

    async def _ensure_initialized(self) -> None:
        """Initialize the database schema on first use."""
        if not self._initialized:
            await asyncio.to_thread(self._init_schema)
            self._initialized = True
