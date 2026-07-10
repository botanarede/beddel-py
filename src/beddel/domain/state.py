"""Thread-safe versioned state container with compare-and-swap (CAS) semantics.

Provides :class:`VersionedState`, an asyncio-safe state container used by
:class:`~beddel.domain.strategies.parallel.ParallelExecutionStrategy` to
protect shared ``context.step_results`` writes when two or more parallel
steps in the same group target the same output key.

Each key is stored alongside a monotonically increasing version number.
Writers must supply the expected version they read; a mismatch raises
:exc:`~beddel.domain.errors.StateConflictError`, enabling optimistic
concurrency control (OCC) via a retry-with-jitter loop at the call site.
"""

from __future__ import annotations

import asyncio
from typing import Any

from beddel.domain.errors import StateConflictError

__all__ = [
    "VersionedState",
]


class VersionedState:
    """Thread-safe state container with compare-and-swap (CAS) semantics.

    Internal storage maps each key to a ``(value, version)`` tuple.  A
    single :class:`asyncio.Lock` serialises all ``get``/``set`` calls so
    that version reads and conditional writes are atomic with respect to
    the event loop.

    A brand-new (missing) key has an implicit version of ``0``; the first
    successful :meth:`set` with ``expected_version=0`` produces version
    ``1``.
    """

    def __init__(self) -> None:
        self._data: dict[str, tuple[Any, int]] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> tuple[Any, int]:
        """Return the current value and version for *key*.

        Args:
            key: The state key to look up.

        Returns:
            A ``(value, version)`` tuple.  If *key* has never been written,
            returns ``(None, 0)``.
        """
        async with self._lock:
            return self._data.get(key, (None, 0))

    async def set(self, key: str, value: Any, expected_version: int) -> int:
        """Set *key* to *value* if the current version matches *expected_version*.

        This is the compare-and-swap (CAS) primitive: the write succeeds
        only when the caller's view of the version is still current.

        Args:
            key: The state key to write.
            value: The new value to store.
            expected_version: The version the caller last observed for
                *key*.  Must equal the current stored version for the
                write to succeed.

        Returns:
            The new version number (``expected_version + 1``) on success.

        Raises:
            StateConflictError: If ``expected_version`` does not match the
                key's current version (another writer incremented it since
                the caller's last :meth:`get`).
        """
        async with self._lock:
            _, current_version = self._data.get(key, (None, 0))
            if current_version != expected_version:
                raise StateConflictError(
                    key=key,
                    expected=expected_version,
                    actual=current_version,
                )
            new_version = current_version + 1
            self._data[key] = (value, new_version)
            return new_version
