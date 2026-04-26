"""Beddel ag-ui-kit — AG-UI protocol adapter for dashboard integration.

Re-exports the public API from the kit's modules:

- :class:`BeddelAGUIAdapter` — AG-UI adapter for workflow event streams
- :func:`create_agui_endpoint` — FastAPI AG-UI endpoint factory
- :func:`create_unified_agui_endpoint` — Unified multi-workflow AG-UI endpoint factory
- :func:`create_workflow_listing_router` — Workflow listing endpoint factory
"""

from __future__ import annotations

__all__ = [
    "BeddelAGUIAdapter",
    "create_agui_endpoint",
    "create_unified_agui_endpoint",
    "create_workflow_listing_router",
]


def __getattr__(name: str) -> object:
    """Lazy-load kit symbols to avoid import-time side effects."""
    if name == "BeddelAGUIAdapter":
        from beddel_ag_ui.adapter import BeddelAGUIAdapter

        return BeddelAGUIAdapter
    if name == "create_agui_endpoint":
        from beddel_ag_ui.endpoint import create_agui_endpoint

        return create_agui_endpoint
    if name == "create_unified_agui_endpoint":
        from beddel_ag_ui.unified import create_unified_agui_endpoint

        return create_unified_agui_endpoint
    if name == "create_workflow_listing_router":
        from beddel_ag_ui.listing import create_workflow_listing_router

        return create_workflow_listing_router
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
