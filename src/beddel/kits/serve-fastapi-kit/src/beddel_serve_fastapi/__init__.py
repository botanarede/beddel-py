"""Beddel serve-fastapi-kit — FastAPI serving + SSE.

Re-exports the public API from the kit's modules:

- :func:`create_beddel_handler` — one-line workflow-to-endpoint factory
- :class:`BeddelSSEAdapter` — SSE adapter for workflow event streams
"""

from __future__ import annotations

__all__ = ["BeddelSSEAdapter", "create_beddel_handler"]


def __getattr__(name: str) -> object:
    """Lazy-load kit symbols to avoid import-time side effects."""
    if name == "create_beddel_handler":
        from beddel_serve_fastapi.handler import create_beddel_handler

        return create_beddel_handler
    if name == "BeddelSSEAdapter":
        from beddel_serve_fastapi.sse import BeddelSSEAdapter

        return BeddelSSEAdapter
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
