"""Parametrized deprecation tests for the 8 provider/integration entries in _DEPRECATED_IMPORTS.

Verifies that importing provider, observability, protocol, and auth adapters
via ``beddel.adapters`` emits ``DeprecationWarning`` with the correct kit
module name (AC 9 — Story 5.1.4).

Completes the coverage started in Story 5.1.3 (agent adapters).
"""

from __future__ import annotations

import sys
import warnings

import pytest

import beddel.adapters as _adapters_mod

# ---------------------------------------------------------------------------
# Parametrized test data — all 8 remaining _DEPRECATED_IMPORTS entries
# ---------------------------------------------------------------------------
_PROVIDER_INTEGRATION_PARAMS = [
    ("LiteLLMAdapter", "beddel_provider_litellm"),
    ("OpenTelemetryAdapter", "beddel_observability_otel"),
    ("LangfuseTracerAdapter", "beddel_observability_langfuse"),
    ("StdioMCPClient", "beddel_protocol_mcp"),
    ("SSEMCPClient", "beddel_protocol_mcp"),
    ("delete_credentials", "beddel_auth_github"),
    ("load_credentials", "beddel_auth_github"),
    ("save_credentials", "beddel_auth_github"),
]


@pytest.mark.parametrize("name,expected_kit_module", _PROVIDER_INTEGRATION_PARAMS)
def test_provider_integration_deprecation_warning(
    name: str,
    expected_kit_module: str,
) -> None:
    """Each provider/integration import via beddel.adapters emits DeprecationWarning."""
    # Clear cached lazy import so __getattr__ fires again.
    _adapters_mod.__dict__.pop(name, None)

    # Purge cached kit modules so importlib re-imports them via __getattr__.
    for mod_name in list(sys.modules):
        if mod_name.startswith(expected_kit_module):
            del sys.modules[mod_name]

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        obj = getattr(_adapters_mod, name)

        assert len(w) == 1, f"Expected 1 warning for {name!r}, got {len(w)}"
        assert issubclass(w[0].category, DeprecationWarning)
        assert expected_kit_module in str(w[0].message)
        assert obj is not None


def test_nonexistent_provider_raises_attribute_error() -> None:
    """Accessing an unknown name on beddel.adapters raises AttributeError."""
    with pytest.raises(AttributeError, match="NonExistentProvider"):
        _adapters_mod.NonExistentProvider  # noqa: B018
