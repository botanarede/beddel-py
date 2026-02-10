"""Framework integrations — FastAPI (optional extra)."""

__all__: list[str] = []

try:
    from beddel.integrations.fastapi import create_beddel_handler

    __all__ = ["create_beddel_handler"]  # type: ignore[no-redef]
except ImportError:
    pass
