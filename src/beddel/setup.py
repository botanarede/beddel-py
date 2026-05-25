"""Public setup function for Python API users to activate kit paths."""

from __future__ import annotations

import sys
from pathlib import Path


def _resolve_kit_src_dir(kit_dir: Path) -> Path | None:
    """Resolve the source subdirectory for a kit.

    Checks for 'python/' first (polyglot layout), falls back to 'src/'
    (legacy layout). Returns None if neither exists.
    """
    python_dir = kit_dir / "python"
    if python_dir.is_dir():
        return python_dir
    src_dir = kit_dir / "src"
    if src_dir.is_dir():
        return src_dir
    return None


def setup() -> None:
    """Activate kit paths so kit modules are importable.

    Reads the kits_path from the SQLite database (set during `beddel init`)
    and adds each kit's source directory to `sys.path`.

    Safe to call multiple times (idempotent).

    Example::

        import beddel
        beddel.setup()
        from beddel_provider_litellm.adapter import LiteLLMAdapter
    """
    kits_path = _resolve_kits_path()
    if kits_path is None:
        return

    if kits_path.is_dir():
        for kit_dir in kits_path.iterdir():
            kit_src = _resolve_kit_src_dir(kit_dir)
            if kit_src and str(kit_src) not in sys.path:
                sys.path.insert(0, str(kit_src))

    # Project-local kits (cwd/kits/) — convenience for development
    local_kits = Path.cwd() / "kits"
    if local_kits.is_dir():
        for kit_dir in local_kits.iterdir():
            kit_src = _resolve_kit_src_dir(kit_dir)
            if kit_src and str(kit_src) not in sys.path:
                sys.path.insert(0, str(kit_src))


def _resolve_kits_path() -> Path | None:
    """Read kits_path from SQLite (set by beddel init).

    Returns None if the database doesn't exist or the pref isn't set.
    """
    db_path = Path.home() / ".config" / "beddel" / "index.db"
    if not db_path.exists():
        return None

    try:
        import sqlite3

        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute("SELECT value FROM user_prefs WHERE key = 'kits_path'")
        row = cursor.fetchone()
        conn.close()
        if row:
            return Path(row[0])
    except Exception:
        pass

    return None
