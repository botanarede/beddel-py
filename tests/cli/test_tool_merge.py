"""Integration tests for 3-layer tool registry merge in CLI commands.

Verifies the merge order: discover_builtin_tools() (base) →
inline YAML tools (override) → --tool CLI flags (final override).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from unittest.mock import patch

from beddel.domain.models import Workflow


def _fake_builtin_a(**kwargs: Any) -> str:
    return "builtin_a"


def _fake_builtin_b(**kwargs: Any) -> str:
    return "builtin_b"


def _fake_inline(**kwargs: Any) -> str:
    return "inline"


def _fake_cli(**kwargs: Any) -> str:
    return "cli"


class TestBuildToolRegistry:
    """Tests for the _build_tool_registry helper function."""

    def test_builtins_available_without_overrides(self) -> None:
        """Builtin tools appear in merged registry when no overrides given."""
        from beddel.cli.commands import _build_tool_registry

        builtins = {"builtin_a": _fake_builtin_a, "builtin_b": _fake_builtin_b}
        wf = Workflow(
            id="t",
            name="t",
            steps=[{"id": "s1", "primitive": "llm"}],  # type: ignore[list-item]
        )

        with patch("beddel.tools.discover_builtin_tools", return_value=builtins):
            merged = _build_tool_registry(wf, {})

        assert merged["builtin_a"] is _fake_builtin_a
        assert merged["builtin_b"] is _fake_builtin_b

    def test_inline_yaml_overrides_builtin(self) -> None:
        """Inline YAML tool with same name overrides the builtin."""
        from beddel.cli.commands import _build_tool_registry

        builtins: dict[str, Callable[..., Any]] = {"shared": _fake_builtin_a}
        wf = Workflow(
            id="t",
            name="t",
            steps=[{"id": "s1", "primitive": "llm"}],  # type: ignore[list-item]
        )
        wf.metadata["_inline_tools"] = {"shared": _fake_inline}

        with patch("beddel.tools.discover_builtin_tools", return_value=builtins):
            merged = _build_tool_registry(wf, {})

        assert merged["shared"] is _fake_inline

    def test_cli_flag_overrides_both(self) -> None:
        """CLI --tool flag overrides both builtins and inline YAML tools."""
        from beddel.cli.commands import _build_tool_registry

        builtins: dict[str, Callable[..., Any]] = {"shared": _fake_builtin_a}
        wf = Workflow(
            id="t",
            name="t",
            steps=[{"id": "s1", "primitive": "llm"}],  # type: ignore[list-item]
        )
        wf.metadata["_inline_tools"] = {"shared": _fake_inline}
        parsed_tools: dict[str, Callable[..., Any]] = {"shared": _fake_cli}

        with patch("beddel.tools.discover_builtin_tools", return_value=builtins):
            merged = _build_tool_registry(wf, parsed_tools)

        assert merged["shared"] is _fake_cli

    def test_all_three_layers_coexist(self) -> None:
        """Non-overlapping tools from all 3 layers are all present."""
        from beddel.cli.commands import _build_tool_registry

        builtins: dict[str, Callable[..., Any]] = {"from_builtin": _fake_builtin_a}
        wf = Workflow(
            id="t",
            name="t",
            steps=[{"id": "s1", "primitive": "llm"}],  # type: ignore[list-item]
        )
        wf.metadata["_inline_tools"] = {"from_inline": _fake_inline}
        parsed_tools: dict[str, Callable[..., Any]] = {"from_cli": _fake_cli}

        with patch("beddel.tools.discover_builtin_tools", return_value=builtins):
            merged = _build_tool_registry(wf, parsed_tools)

        assert merged["from_builtin"] is _fake_builtin_a
        assert merged["from_inline"] is _fake_inline
        assert merged["from_cli"] is _fake_cli

    def test_no_inline_tools_key_in_metadata(self) -> None:
        """Workflow without _inline_tools metadata still works."""
        from beddel.cli.commands import _build_tool_registry

        builtins: dict[str, Callable[..., Any]] = {"b": _fake_builtin_a}
        wf = Workflow(
            id="t",
            name="t",
            steps=[{"id": "s1", "primitive": "llm"}],  # type: ignore[list-item]
        )
        # No _inline_tools in metadata

        with patch("beddel.tools.discover_builtin_tools", return_value=builtins):
            merged = _build_tool_registry(wf, {})

        assert merged["b"] is _fake_builtin_a
