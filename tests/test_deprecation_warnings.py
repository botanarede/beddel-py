"""Tests for deprecation warnings on moved symbols (Story 8.1).

Verifies that importing adapter/integration/primitive symbols from the
top-level ``beddel`` namespace emits ``DeprecationWarning`` with the
correct migration message, while importing from the canonical submodule
does NOT warn.
"""

from __future__ import annotations

import warnings

import pytest


class TestDeprecationWarnings:
    """Verify deprecated top-level imports emit DeprecationWarning."""

    @staticmethod
    def _import_from_beddel(name: str) -> object:
        """Import *name* from ``beddel`` top-level, forcing ``__getattr__``.

        Clears any cached value so the deprecation path fires even if a
        previous test already resolved the same symbol in this process.
        """
        import beddel

        # Remove cached global so __getattr__ fires again.
        if name in vars(beddel):
            delattr(beddel, name)

        return getattr(beddel, name)

    # ------------------------------------------------------------------
    # Subtask 3.1 — adapter / integration / primitive symbols warn
    # ------------------------------------------------------------------

    def test_adapter_in_memory_event_store_warns(self) -> None:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            self._import_from_beddel("InMemoryEventStore")

        dep_warnings = [w for w in caught if issubclass(w.category, DeprecationWarning)]
        assert len(dep_warnings) == 1
        msg = str(dep_warnings[0].message)
        assert "InMemoryEventStore" in msg
        assert "beddel.adapters" in msg
        assert "deprecated" in msg.lower()
        assert "v1.0" in msg

    def test_adapter_static_tier_router_warns(self) -> None:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            self._import_from_beddel("StaticTierRouter")

        dep_warnings = [w for w in caught if issubclass(w.category, DeprecationWarning)]
        assert len(dep_warnings) == 1
        msg = str(dep_warnings[0].message)
        assert "StaticTierRouter" in msg
        assert "beddel.adapters" in msg

    def test_integration_create_beddel_handler_warns(self) -> None:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            self._import_from_beddel("create_beddel_handler")

        dep_warnings = [w for w in caught if issubclass(w.category, DeprecationWarning)]
        assert len(dep_warnings) == 1
        msg = str(dep_warnings[0].message)
        assert "create_beddel_handler" in msg
        assert "beddel.integrations" in msg

    def test_primitive_agent_exec_warns(self) -> None:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            self._import_from_beddel("AgentExecPrimitive")

        dep_warnings = [w for w in caught if issubclass(w.category, DeprecationWarning)]
        assert len(dep_warnings) == 1
        msg = str(dep_warnings[0].message)
        assert "AgentExecPrimitive" in msg
        assert "beddel.primitives.agent_exec" in msg

    # ------------------------------------------------------------------
    # Subtask 3.2 — canonical submodule imports do NOT warn
    # ------------------------------------------------------------------

    def test_adapters_import_no_warning(self) -> None:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            from beddel.adapters import InMemoryEventStore  # noqa: F811

        dep_warnings = [w for w in caught if issubclass(w.category, DeprecationWarning)]
        assert dep_warnings == [], (
            f"Expected no DeprecationWarning from beddel.adapters, got: {dep_warnings}"
        )
        assert InMemoryEventStore is not None

    def test_integrations_import_no_warning(self) -> None:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            from beddel.integrations import create_beddel_handler  # noqa: F811

        dep_warnings = [w for w in caught if issubclass(w.category, DeprecationWarning)]
        assert dep_warnings == [], (
            f"Expected no DeprecationWarning from beddel.integrations, got: {dep_warnings}"
        )
        assert create_beddel_handler is not None

    # ------------------------------------------------------------------
    # Subtask 3.3 — deprecated imports still return the correct object
    # ------------------------------------------------------------------

    def test_deprecated_import_returns_correct_adapter(self) -> None:
        from beddel.adapters import InMemoryEventStore as canonical

        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            deprecated = self._import_from_beddel("InMemoryEventStore")

        assert deprecated is canonical

    def test_deprecated_import_returns_correct_integration(self) -> None:
        from beddel.integrations import create_beddel_handler as canonical

        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            deprecated = self._import_from_beddel("create_beddel_handler")

        assert deprecated is canonical

    def test_deprecated_import_returns_correct_primitive(self) -> None:
        from beddel.primitives.agent_exec import AgentExecPrimitive as canonical

        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            deprecated = self._import_from_beddel("AgentExecPrimitive")

        assert deprecated is canonical

    # ------------------------------------------------------------------
    # Edge: unknown attribute still raises AttributeError
    # ------------------------------------------------------------------

    def test_unknown_attribute_raises(self) -> None:
        import beddel

        with pytest.raises(AttributeError, match="no_such_symbol_xyz"):
            _ = beddel.no_such_symbol_xyz  # type: ignore[attr-defined]
