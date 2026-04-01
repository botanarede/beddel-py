"""Parametrized deprecation tests for all 4 agent adapter entries in _DEPRECATED_IMPORTS.

Verifies that importing agent adapters via ``beddel.adapters`` emits
``DeprecationWarning`` with the correct kit module name (AC 8, 9 — Story 5.1.3).
"""

from __future__ import annotations

import sys
import warnings
from unittest.mock import MagicMock

import pytest

# Mock claude_agent_sdk before any adapter import triggers it (not installed).
if "claude_agent_sdk" not in sys.modules:
    sys.modules["claude_agent_sdk"] = MagicMock()

import beddel.adapters as _adapters_mod  # noqa: E402

_AGENT_ADAPTER_PARAMS = [
    ("OpenClawAgentAdapter", "beddel_agent_openclaw"),
    ("ClaudeAgentAdapter", "beddel_agent_claude"),
    ("CodexAgentAdapter", "beddel_agent_codex"),
    ("KiroCLIAgentAdapter", "beddel_agent_kiro"),
]


@pytest.mark.parametrize("adapter_name,expected_kit_module", _AGENT_ADAPTER_PARAMS)
def test_agent_adapter_deprecation_warning(
    adapter_name: str,
    expected_kit_module: str,
) -> None:
    """Each agent adapter import via beddel.adapters emits DeprecationWarning."""
    # Clear cached lazy import so __getattr__ fires again.
    _adapters_mod.__dict__.pop(adapter_name, None)

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        obj = getattr(_adapters_mod, adapter_name)

        assert len(w) == 1
        assert issubclass(w[0].category, DeprecationWarning)
        assert expected_kit_module in str(w[0].message)
        assert obj is not None


def test_nonexistent_adapter_raises_attribute_error() -> None:
    """Accessing an unknown name on beddel.adapters raises AttributeError."""
    with pytest.raises(AttributeError, match="NonExistentAdapter"):
        _adapters_mod.NonExistentAdapter  # noqa: B018
