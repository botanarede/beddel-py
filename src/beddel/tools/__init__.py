"""Beddel tools — decorator and auto-discovery for builtin tool functions.

Provides :func:`beddel_tool` — a decorator that marks a function as a
discoverable Beddel tool — and :func:`discover_builtin_tools` which scans
all ``beddel.tools.*`` submodules to collect decorated tools into a registry.
"""

from __future__ import annotations

import importlib
import logging
import pkgutil
from collections.abc import Callable
from typing import Any, TypeVar

F = TypeVar("F", bound=Callable[..., Any])

logger = logging.getLogger(__name__)

__all__ = [
    "beddel_tool",
    "discover_builtin_tools",
]


def beddel_tool(name: str, description: str = "", category: str = "general") -> Callable[[F], F]:
    """Decorator that marks a function as a discoverable Beddel tool.

    Stores metadata on the decorated function as ``_beddel_tool_meta``.

    Args:
        name: Unique tool name used for registry lookup.
        description: Human-readable description of the tool.
        category: Tool category (e.g. ``"shell"``, ``"file"``, ``"http"``).

    Returns:
        A decorator that attaches metadata and returns the function unchanged.
    """

    def decorator(fn: F) -> F:
        fn._beddel_tool_meta = {  # type: ignore[attr-defined]
            "name": name,
            "description": description,
            "category": category,
        }
        return fn

    return decorator


def discover_builtin_tools() -> dict[str, Callable[..., Any]]:
    """Scan ``beddel.tools.*`` submodules and collect decorated tools.

    Uses ``pkgutil.iter_modules`` to find submodules of the ``beddel.tools``
    package, imports each one, and collects functions that have the
    ``_beddel_tool_meta`` attribute (set by :func:`beddel_tool`).

    Returns:
        Dict mapping tool names to their callable implementations.
    """
    tools: dict[str, Callable[..., Any]] = {}
    package = importlib.import_module("beddel.tools")
    for _importer, modname, _ispkg in pkgutil.iter_modules(package.__path__):
        try:
            mod = importlib.import_module(f"beddel.tools.{modname}")
        except ImportError:
            logger.warning("Failed to import beddel.tools.%s", modname)
            continue
        for attr_name in dir(mod):
            obj = getattr(mod, attr_name)
            if callable(obj) and hasattr(obj, "_beddel_tool_meta"):
                meta: dict[str, str] = obj._beddel_tool_meta
                tools[meta["name"]] = obj
    return tools
