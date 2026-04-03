"""State store adapters for workflow checkpoint persistence.

Provides two :class:`~beddel.domain.ports.IStateStore` implementations:

- :class:`InMemoryStateStore` — dict-based in-memory storage for testing.
- :class:`JSONFileStateStore` — persistent JSON file-backed storage with
  atomic writes and file locking for concurrent safety.
"""

from __future__ import annotations

import asyncio
import contextlib
import fcntl
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from beddel.domain.errors import StateError
from beddel.error_codes import (
    STATE_CORRUPTED,
    STATE_DELETE_FAILED,
    STATE_LOAD_FAILED,
    STATE_SAVE_FAILED,
)


def _validate_workflow_id(workflow_id: str) -> None:
    """Reject workflow IDs that could cause path traversal."""
    if not workflow_id:
        msg = "workflow_id must not be empty"
        raise ValueError(msg)
    if "\x00" in workflow_id:
        msg = "workflow_id must not contain null bytes"
        raise ValueError(msg)
    if "/" in workflow_id or "\\" in workflow_id:
        msg = "workflow_id must not contain path separators"
        raise ValueError(msg)
    if ".." in workflow_id:
        msg = "workflow_id must not contain '..'"
        raise ValueError(msg)


class InMemoryStateStore:
    """Dict-based in-memory state store for testing.

    Satisfies the :class:`~beddel.domain.ports.IStateStore` protocol
    via structural subtyping.
    """

    def __init__(self) -> None:
        self._store: dict[str, dict[str, Any]] = {}

    async def save(self, workflow_id: str, state: dict[str, Any]) -> None:
        """Persist state in memory."""
        self._store[workflow_id] = dict(state)

    async def load(self, workflow_id: str) -> dict[str, Any] | None:
        """Load state from memory, or ``None`` if not present."""
        stored = self._store.get(workflow_id)
        return dict(stored) if stored is not None else None

    async def delete(self, workflow_id: str) -> None:
        """Remove state from memory. No-op if not present."""
        self._store.pop(workflow_id, None)


class JSONFileStateStore:
    """Persistent JSON file-backed state store.

    Satisfies the :class:`~beddel.domain.ports.IStateStore` protocol
    via structural subtyping.  Uses atomic writes (temp file + rename)
    and ``fcntl.flock(LOCK_EX)`` for concurrent safety.

    File naming: ``{directory}/{workflow_id}.json``.
    """

    def __init__(self, directory: str | Path = ".beddel-state") -> None:
        self._directory = Path(directory)
        self._directory.mkdir(parents=True, exist_ok=True)

    def _path_for(self, workflow_id: str) -> Path:
        """Return the JSON file path for a workflow ID."""
        _validate_workflow_id(workflow_id)
        return self._directory / f"{workflow_id}.json"

    async def save(self, workflow_id: str, state: dict[str, Any]) -> None:
        """Persist state as a JSON file with atomic write and file locking."""

        def _write() -> None:
            target = self._path_for(workflow_id)
            fd_int = -1
            tmp_name = ""
            try:
                data = json.dumps(state, indent=2, default=str)
                fd_int, tmp_name = tempfile.mkstemp(
                    suffix=".tmp",
                    dir=str(self._directory),
                )
                fcntl.flock(fd_int, fcntl.LOCK_EX)
                os.write(fd_int, data.encode())
                os.fsync(fd_int)
                fcntl.flock(fd_int, fcntl.LOCK_UN)
                os.close(fd_int)
                fd_int = -1
                os.rename(tmp_name, str(target))
                tmp_name = ""
            except StateError:
                raise
            except Exception as exc:
                raise StateError(
                    STATE_SAVE_FAILED,
                    f"Failed to save state for workflow {workflow_id!r}: {exc}",
                ) from exc
            finally:
                if fd_int >= 0:
                    with contextlib.suppress(OSError):
                        os.close(fd_int)
                if tmp_name:
                    with contextlib.suppress(OSError):
                        os.unlink(tmp_name)

        await asyncio.to_thread(_write)

    async def load(self, workflow_id: str) -> dict[str, Any] | None:
        """Load state from a JSON file, or ``None`` if not found."""

        def _read() -> dict[str, Any] | None:
            target = self._path_for(workflow_id)
            if not target.exists():
                return None
            try:
                with open(target) as f:
                    fcntl.flock(f.fileno(), fcntl.LOCK_SH)
                    data = f.read()
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            except Exception as exc:
                raise StateError(
                    STATE_LOAD_FAILED,
                    f"Failed to read state for workflow {workflow_id!r}: {exc}",
                ) from exc
            try:
                return json.loads(data)  # type: ignore[no-any-return]
            except json.JSONDecodeError as exc:
                raise StateError(
                    STATE_CORRUPTED,
                    f"Corrupted state for workflow {workflow_id!r}: {exc}",
                ) from exc

        return await asyncio.to_thread(_read)

    async def delete(self, workflow_id: str) -> None:
        """Remove the JSON file for a workflow. No-op if not found."""

        def _delete() -> None:
            target = self._path_for(workflow_id)
            try:
                target.unlink(missing_ok=True)
            except Exception as exc:
                raise StateError(
                    STATE_DELETE_FAILED,
                    f"Failed to delete state for workflow {workflow_id!r}: {exc}",
                ) from exc

        await asyncio.to_thread(_delete)
