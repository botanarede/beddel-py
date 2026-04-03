"""Integration tests for 3-layer tool registry merge in CLI commands.

Verifies the merge order: kit tools (layer 1) →
inline YAML tools (layer 2) → --tool CLI flags (layer 3).

After Story 6.1.1, ``discover_builtin_tools()`` is no longer called as a
separate merge layer.  Kit tools are now layer 1.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import patch

from beddel.domain.models import Workflow


def _fake_inline(**kwargs: Any) -> str:
    return "inline"


def _fake_cli(**kwargs: Any) -> str:
    return "cli"


class TestBuildToolRegistry:
    """Tests for the _build_tool_registry helper function."""

    def test_empty_when_no_kits_no_overrides(self) -> None:
        """Registry is empty when no_kits=True and no overrides given."""
        from beddel.cli.commands import _build_tool_registry

        wf = Workflow(
            id="t",
            name="t",
            steps=[{"id": "s1", "primitive": "llm"}],  # type: ignore[list-item]
        )

        merged = _build_tool_registry(wf, {}, no_kits=True)

        assert merged == {}

    def test_inline_yaml_present(self) -> None:
        """Inline YAML tools appear in merged registry."""
        from beddel.cli.commands import _build_tool_registry

        wf = Workflow(
            id="t",
            name="t",
            steps=[{"id": "s1", "primitive": "llm"}],  # type: ignore[list-item]
        )
        wf.metadata["_inline_tools"] = {"shared": _fake_inline}

        merged = _build_tool_registry(wf, {}, no_kits=True)

        assert merged["shared"] is _fake_inline

    def test_cli_flag_overrides_inline(self) -> None:
        """CLI --tool flag overrides inline YAML tools."""
        from beddel.cli.commands import _build_tool_registry

        wf = Workflow(
            id="t",
            name="t",
            steps=[{"id": "s1", "primitive": "llm"}],  # type: ignore[list-item]
        )
        wf.metadata["_inline_tools"] = {"shared": _fake_inline}
        parsed_tools: dict[str, Callable[..., Any]] = {"shared": _fake_cli}

        merged = _build_tool_registry(wf, parsed_tools, no_kits=True)

        assert merged["shared"] is _fake_cli

    def test_all_three_layers_coexist(self) -> None:
        """Non-overlapping tools from all 3 layers are all present."""
        from beddel.cli.commands import _build_tool_registry
        from beddel.domain.kit import (
            KitDiscoveryResult,
            KitManifest,
            KitToolDeclaration,
            SolutionKit,
        )

        _fake_kit = lambda: "kit"  # noqa: E731

        kit_manifest = KitManifest(
            kit=SolutionKit(
                name="my-kit",
                version="0.1.0",
                description="t",
                tools=[KitToolDeclaration(name="from_kit", target="json:dumps")],
            ),
            root_path=Path("/fake"),
            loaded_at=__import__("datetime").datetime.now(tz=__import__("datetime").UTC),
        )
        discovery = KitDiscoveryResult(manifests=[kit_manifest], collisions=[])

        wf = Workflow(
            id="t",
            name="t",
            steps=[{"id": "s1", "primitive": "llm"}],  # type: ignore[list-item]
        )
        wf.metadata["_inline_tools"] = {"from_inline": _fake_inline}
        parsed_tools: dict[str, Callable[..., Any]] = {"from_cli": _fake_cli}

        with (
            patch("beddel.tools.kits.discover_kits", return_value=discovery),
            patch(
                "beddel.tools.kits.load_kit",
                return_value={"from_kit": _fake_kit},
            ),
        ):
            merged = _build_tool_registry(wf, parsed_tools)

        assert merged["from_kit"] is _fake_kit
        assert merged["from_inline"] is _fake_inline
        assert merged["from_cli"] is _fake_cli

    def test_no_inline_tools_key_in_metadata(self) -> None:
        """Workflow without _inline_tools metadata still works."""
        from beddel.cli.commands import _build_tool_registry

        wf = Workflow(
            id="t",
            name="t",
            steps=[{"id": "s1", "primitive": "llm"}],  # type: ignore[list-item]
        )
        # No _inline_tools in metadata

        merged = _build_tool_registry(wf, {}, no_kits=True)

        assert merged == {}

    def test_discover_builtin_tools_not_called(self) -> None:
        """discover_builtin_tools() is NOT called during _build_tool_registry()."""
        from beddel.cli.commands import _build_tool_registry
        from beddel.domain.kit import KitDiscoveryResult

        wf = Workflow(
            id="t",
            name="t",
            steps=[{"id": "s1", "primitive": "llm"}],  # type: ignore[list-item]
        )

        discovery = KitDiscoveryResult(manifests=[], collisions=[])

        with (
            patch("beddel.tools.kits.discover_kits", return_value=discovery),
            patch("beddel.tools.discover_builtin_tools") as mock_builtin,
        ):
            _build_tool_registry(wf, {})

        mock_builtin.assert_not_called()

    def test_kit_tools_are_layer_1_in_merge(self) -> None:
        """Kit tools are the base layer — overridden by inline and CLI."""
        from beddel.cli.commands import _build_tool_registry
        from beddel.domain.kit import (
            KitDiscoveryResult,
            KitManifest,
            KitToolDeclaration,
            SolutionKit,
        )

        kit_manifest = KitManifest(
            kit=SolutionKit(
                name="base-kit",
                version="0.1.0",
                description="t",
                tools=[KitToolDeclaration(name="tool-a", target="json:dumps")],
            ),
            root_path=Path("/fake"),
            loaded_at=__import__("datetime").datetime.now(tz=__import__("datetime").UTC),
        )
        discovery = KitDiscoveryResult(manifests=[kit_manifest], collisions=[])

        wf = Workflow(
            id="t",
            name="t",
            steps=[{"id": "s1", "primitive": "llm"}],  # type: ignore[list-item]
        )
        # Inline overrides kit
        wf.metadata["_inline_tools"] = {"tool-a": _fake_inline}

        with (
            patch("beddel.tools.kits.discover_kits", return_value=discovery),
            patch(
                "beddel.tools.kits.load_kit",
                return_value={"tool-a": lambda: "kit"},
            ),
        ):
            merged = _build_tool_registry(wf, {})

        # Inline (layer 2) overrides kit (layer 1)
        assert merged["tool-a"] is _fake_inline


# ---------------------------------------------------------------------------
# kit_list — SOURCE column output
# ---------------------------------------------------------------------------


class TestKitListSourceColumn:
    """Tests for `beddel kit list` SOURCE column output."""

    def test_source_column_in_output(self) -> None:
        """kit_list displays SOURCE column with correct values."""
        from datetime import UTC, datetime

        from click.testing import CliRunner

        from beddel.cli.commands import cli
        from beddel.domain.kit import (
            KitDiscoveryResult,
            KitManifest,
            SolutionKit,
        )

        bundled_manifest = KitManifest(
            kit=SolutionKit(
                name="bundled-kit",
                version="0.1.0",
                description="t",
                tools=[],
            ),
            root_path=Path("/fake/bundled"),
            loaded_at=datetime.now(tz=UTC),
            source="bundled",
        )
        local_manifest = KitManifest(
            kit=SolutionKit(
                name="local-kit",
                version="0.2.0",
                description="t",
                tools=[],
            ),
            root_path=Path("/fake/local"),
            loaded_at=datetime.now(tz=UTC),
            source="local",
        )
        discovery = KitDiscoveryResult(manifests=[bundled_manifest, local_manifest], collisions=[])

        runner = CliRunner()
        with (
            patch("beddel.tools.kits.discover_kits", return_value=discovery),
            patch("beddel.tools.kits.load_kit", return_value={}),
            patch("beddel.cli.commands._ensure_kit_paths"),
        ):
            result = runner.invoke(cli, ["kit", "list"])

        assert result.exit_code == 0
        assert "SOURCE" in result.output
        assert "bundled" in result.output
        assert "local" in result.output
