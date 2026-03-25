"""Beddel integrations — framework-specific bindings."""

__all__ = ["BeddelSSEAdapter", "create_beddel_handler", "create_dashboard_router"]


def __getattr__(name: str) -> object:
    """Lazy-load integration symbols for consistent import behavior.

    ``BeddelSSEAdapter`` is deferred for consistency with
    ``create_beddel_handler``, which requires the ``fastapi`` extra.
    """
    if name == "BeddelSSEAdapter":
        from beddel.integrations.sse import BeddelSSEAdapter

        return BeddelSSEAdapter
    if name == "create_beddel_handler":
        from beddel.integrations.fastapi import create_beddel_handler

        return create_beddel_handler
    if name == "create_dashboard_router":
        from beddel.integrations.dashboard import create_dashboard_router

        return create_dashboard_router
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
