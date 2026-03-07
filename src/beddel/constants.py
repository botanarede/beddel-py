"""Shared constants for the Beddel SDK.

This module defines named constants for string literals used across the
codebase, ensuring consistency and enabling safe refactoring.
"""

__all__ = [
    "CALL_DEPTH_KEY",
]

CALL_DEPTH_KEY: str = "_call_depth"
"""Metadata key tracking nested call-agent invocation depth."""
