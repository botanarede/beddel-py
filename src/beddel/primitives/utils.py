"""Shared utility functions for Beddel primitives."""

from __future__ import annotations

from typing import Any

from beddel.domain.errors import PrimitiveError
from beddel.error_codes import PRIM_INVALID_MESSAGE

_REQUIRED_MESSAGE_KEYS: frozenset[str] = frozenset({"role", "content"})


def validate_message(msg: dict[str, Any]) -> None:
    """Validate that a message dict contains required keys.

    Args:
        msg: A message dict to validate.

    Raises:
        PrimitiveError: With code ``BEDDEL-PRIM-006`` if ``role`` or
            ``content`` keys are missing.
    """
    missing = _REQUIRED_MESSAGE_KEYS - msg.keys()
    if missing:
        raise PrimitiveError(
            code=PRIM_INVALID_MESSAGE,
            message=f"Message dict missing required keys: {sorted(missing)}",
            details={"missing_keys": sorted(missing)},
        )
