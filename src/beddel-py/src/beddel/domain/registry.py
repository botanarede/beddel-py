"""Primitive registry — Registration and lookup of workflow primitives."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from beddel.domain.models import ErrorCode, ExecutionContext, ExecutionError

# Type alias for primitive functions: async (config, context) -> Any
PrimitiveFunc = Callable[[dict[str, Any], ExecutionContext], Awaitable[Any]]


class PrimitiveRegistry:
    """Manage registration and lookup of workflow primitives.

    Usage::

        registry = PrimitiveRegistry()

        @registry.register("llm")
        async def llm_primitive(config: dict, context: ExecutionContext) -> Any:
            ...

        fn = registry.get("llm")
    """

    def __init__(self) -> None:
        self._primitives: dict[str, PrimitiveFunc] = {}

    def register(self, name: str) -> Callable[[PrimitiveFunc], PrimitiveFunc]:
        """Decorator to register a primitive function by name."""

        def decorator(fn: PrimitiveFunc) -> PrimitiveFunc:
            if name in self._primitives:
                raise ValueError(f"Primitive '{name}' is already registered")
            self._primitives[name] = fn
            return fn

        return decorator

    def register_func(self, name: str, fn: PrimitiveFunc) -> None:
        """Imperatively register a primitive function."""
        if name in self._primitives:
            raise ValueError(f"Primitive '{name}' is already registered")
        self._primitives[name] = fn

    def get(self, name: str) -> PrimitiveFunc:
        """Look up a registered primitive by name."""
        try:
            return self._primitives[name]
        except KeyError:
            raise ExecutionError(
                f"Primitive '{name}' not found in registry",
                code=ErrorCode.EXEC_PRIMITIVE_NOT_FOUND,
                details={"primitive": name, "available": list(self._primitives.keys())},
            ) from None

    def list(self) -> list[str]:
        """Return names of all registered primitives."""
        return sorted(self._primitives.keys())

    def has(self, name: str) -> bool:
        """Check if a primitive is registered."""
        return name in self._primitives
