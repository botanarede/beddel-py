"""Primitive registry for the Beddel SDK.

Provides :class:`PrimitiveRegistry` — a thread-safe, in-memory mapping of
primitive names to :class:`~beddel.domain.ports.IPrimitive` implementations —
and the :func:`primitive` convenience decorator that registers classes in the
module-level :data:`default_registry`.

The registry is consumed by the ``WorkflowExecutor`` to look up primitives by
the ``step.primitive`` field at execution time.
"""

from __future__ import annotations

from typing import Any

from beddel.domain.errors import PrimitiveError
from beddel.domain.ports import IPrimitive

__all__ = [
    "PrimitiveRegistry",
    "default_registry",
    "primitive",
]


class PrimitiveRegistry:
    """In-memory registry that maps primitive names to ``IPrimitive`` instances.

    Example::

        registry = PrimitiveRegistry()
        registry.register("my-prim", MyPrimitive())
        prim = registry.get("my-prim")
    """

    def __init__(self) -> None:
        """Initialise the registry with an empty primitive store."""
        self._primitives: dict[str, IPrimitive] = {}

    def register(self, name: str, primitive: IPrimitive) -> None:
        """Register a primitive instance under the given name.

        Args:
            name: Unique name used to look up the primitive (e.g. ``"llm"``).
            primitive: An object implementing :class:`IPrimitive`.

        Raises:
            PrimitiveError: ``BEDDEL-PRIM-002`` if *primitive* does not
                implement :class:`IPrimitive`.
        """
        if not isinstance(primitive, IPrimitive):
            raise PrimitiveError(
                "BEDDEL-PRIM-002",
                f"Invalid primitive: {type(primitive).__name__} does not implement IPrimitive",
                {"name": name, "type": type(primitive).__name__},
            )
        self._primitives[name] = primitive

    def get(self, name: str) -> IPrimitive:
        """Retrieve a registered primitive by name.

        Args:
            name: The primitive name to look up.

        Returns:
            The :class:`IPrimitive` instance registered under *name*.

        Raises:
            PrimitiveError: ``BEDDEL-PRIM-001`` if no primitive is registered
                under *name*.
        """
        try:
            return self._primitives[name]
        except KeyError:
            raise PrimitiveError(
                "BEDDEL-PRIM-001",
                f"Primitive not found: {name!r}",
                {"name": name},
            ) from None

    def has(self, name: str) -> bool:
        """Check whether a primitive is registered under *name*.

        Args:
            name: The primitive name to check.

        Returns:
            ``True`` if the name is registered, ``False`` otherwise.
        """
        return name in self._primitives

    def list_primitives(self) -> list[str]:
        """Return the names of all registered primitives.

        Returns:
            A sorted list of registered primitive names.
        """
        return sorted(self._primitives)


default_registry = PrimitiveRegistry()
"""Module-level default registry used by the :func:`primitive` decorator."""


def primitive(name: str) -> Any:
    """Class decorator that registers a primitive in :data:`default_registry`.

    The decorated class is instantiated (with no arguments) and the resulting
    instance is registered under *name*.  The original class is returned
    unchanged so it can still be used directly.

    Args:
        name: The name to register the primitive under.

    Returns:
        A class decorator.

    Raises:
        PrimitiveError: ``BEDDEL-PRIM-002`` if the decorated class is not a
            subclass of :class:`IPrimitive`.

    Example::

        @primitive("my-prim")
        class MyPrimitive(IPrimitive):
            async def execute(self, config, context):
                return config["value"]
    """

    def _decorator(cls: type) -> type:
        if not (isinstance(cls, type) and issubclass(cls, IPrimitive)):
            raise PrimitiveError(
                "BEDDEL-PRIM-002",
                f"Invalid primitive: {cls.__name__} does not implement IPrimitive",
                {"name": name, "type": cls.__name__},
            )
        instance = cls()
        default_registry.register(name, instance)
        return cls

    return _decorator
