"""Beddel integrations — framework-specific bindings."""

from beddel.integrations.sse import BeddelSSEAdapter

__all__ = ["BeddelSSEAdapter", "create_beddel_handler"]


def __getattr__(name: str) -> object:
    """Lazy-load FastAPI integration to avoid hard dependency on fastapi.

    The ``create_beddel_handler`` factory is only importable when the
    ``fastapi`` extra is installed.  This ``__getattr__`` defers the
    import so that ``import beddel.integrations`` never fails due to a
    missing ``fastapi`` package.
    """
    if name == "create_beddel_handler":
        from beddel.integrations.fastapi import create_beddel_handler

        return create_beddel_handler
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
