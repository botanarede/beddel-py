"""Tests for deprecated package-level adapter imports (ADR-0008, Story 5.1.1 Task 5)."""

from __future__ import annotations

import warnings

import beddel.adapters as _adapters_mod


def test_package_level_import_emits_deprecation_warning() -> None:
    """Importing a kit-bound adapter via ``beddel.adapters`` emits DeprecationWarning."""
    # Clear any cached lazy import so __getattr__ fires again.
    _adapters_mod.__dict__.pop("LiteLLMAdapter", None)

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        from beddel.adapters import LiteLLMAdapter  # noqa: F811

        assert len(w) == 1
        assert issubclass(w[0].category, DeprecationWarning)
        assert "beddel_provider_litellm" in str(w[0].message)
        assert LiteLLMAdapter is not None
