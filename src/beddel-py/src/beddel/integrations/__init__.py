"""Framework integrations — SSE adapter (always available) and FastAPI (optional extra)."""

from beddel.integrations.sse import BeddelSSEAdapter, SSEEvent

__all__: list[str] = ["BeddelSSEAdapter", "SSEEvent"]

try:
    from beddel.integrations.fastapi import create_beddel_handler

    __all__ += ["create_beddel_handler"]
except ImportError:
    pass
