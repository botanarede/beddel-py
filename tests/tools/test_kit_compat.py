"""Backward compatibility tests for kit integration in _build_tool_registry().

Validates:
- Unnamespaced tool names resolve when no kits loaded (AC #1)
- Inline YAML tools override kit tools — layer 3 > layer 2 (AC #2)
- CLI tools override everything — layer 4 > all (AC #3)
- Deprecation warning when kit tool shadows builtin (AC #5)
- Strict mode raises KitManifestError on collision (AC #6)
- Strict mode does NOT raise when no collisions exist (AC #6)
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from beddel.domain.errors import KitManifestError
from beddel.domain.kit import (
    KitCollision,
    KitDiscoveryResult,
    KitManifest,
    KitToolDeclaration,
    SolutionKit,
)
from beddel.error_codes import KIT_RESOLUTION_AMBIGUOUS

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_manifest(
    name: str = "test-kit",
    tools: list[KitToolDeclaration] | None = None,
) -> KitManifest:
    from datetime import UTC, datetime

    kit = SolutionKit(
        name=name,
        version="0.1.0",
        description=f"Test kit {name}",
        tools=tools or [],
    )
    return KitManifest(
        kit=kit,
        root_path=Path("/fake/kit"),
        loaded_at=datetime.now(tz=UTC),
    )


# ---------------------------------------------------------------------------
# AC #1: Unnamespaced tool names resolve when no kits loaded
# ---------------------------------------------------------------------------


class TestUnnamespacedNoKits:
    """Unnamespaced tool names still resolve when no_kits=True."""

    def test_builtin_tools_resolve_without_kits(self) -> None:
        from beddel.cli.commands import _build_tool_registry

        workflow = MagicMock()
        workflow.metadata = {}

        builtin_tools: dict[str, Callable[..., Any]] = {
            "read_file": lambda: "builtin",
            "shell": lambda: "builtin",
        }

        with patch(
            "beddel.tools.discover_builtin_tools",
            return_value=builtin_tools,
        ):
            result = _build_tool_registry(workflow, {}, no_kits=True)

        assert "read_file" in result
        assert "shell" in result
        assert result["read_file"]() == "builtin"
        assert result["shell"]() == "builtin"


# ---------------------------------------------------------------------------
# AC #2: Inline YAML tools override kit tools (layer 3 > layer 2)
# ---------------------------------------------------------------------------


class TestInlineOverridesKit:
    """Inline YAML tools (layer 3) override kit tools (layer 2)."""

    def test_inline_yaml_wins_over_kit(self) -> None:
        from beddel.cli.commands import _build_tool_registry

        workflow = MagicMock()
        workflow.metadata = {
            "_inline_tools": {"shared_tool": lambda: "inline"},
        }

        kit_manifest = _make_manifest(
            name="my-kit",
            tools=[KitToolDeclaration(name="shared_tool", target="json:dumps")],
        )
        discovery = KitDiscoveryResult(manifests=[kit_manifest], collisions=[])

        with (
            patch("beddel.tools.discover_builtin_tools", return_value={}),
            patch("beddel.tools.kits.discover_kits", return_value=discovery),
            patch(
                "beddel.tools.kits.load_kit",
                return_value={"shared_tool": lambda: "kit"},
            ),
        ):
            result = _build_tool_registry(workflow, {})

        assert result["shared_tool"]() == "inline"


# ---------------------------------------------------------------------------
# AC #3: CLI tools override everything (layer 4 > all)
# ---------------------------------------------------------------------------


class TestCLIOverridesAll:
    """CLI --tool flags (layer 4) override all other layers."""

    def test_cli_wins_over_inline_and_kit_and_builtin(self) -> None:
        from beddel.cli.commands import _build_tool_registry

        workflow = MagicMock()
        workflow.metadata = {
            "_inline_tools": {"shared": lambda: "inline"},
        }

        cli_tools: dict[str, Callable[..., Any]] = {"shared": lambda: "cli"}

        kit_manifest = _make_manifest(
            tools=[KitToolDeclaration(name="shared", target="json:dumps")],
        )
        discovery = KitDiscoveryResult(manifests=[kit_manifest], collisions=[])

        with (
            patch(
                "beddel.tools.discover_builtin_tools",
                return_value={"shared": lambda: "builtin"},
            ),
            patch("beddel.tools.kits.discover_kits", return_value=discovery),
            patch(
                "beddel.tools.kits.load_kit",
                return_value={"shared": lambda: "kit"},
            ),
        ):
            result = _build_tool_registry(workflow, cli_tools)

        assert result["shared"]() == "cli"


# ---------------------------------------------------------------------------
# AC #5: Deprecation warning when kit tool shadows builtin
# ---------------------------------------------------------------------------


class TestShadowWarning:
    """Deprecation warning emitted when a kit tool shadows a builtin."""

    def test_shadow_emits_deprecation_warning(self) -> None:
        from beddel.cli.commands import _build_tool_registry

        workflow = MagicMock()
        workflow.metadata = {}

        kit_manifest = _make_manifest(
            name="my-kit",
            tools=[KitToolDeclaration(name="read_file", target="json:dumps")],
        )
        discovery = KitDiscoveryResult(manifests=[kit_manifest], collisions=[])

        with (
            patch(
                "beddel.tools.discover_builtin_tools",
                return_value={"read_file": lambda: "builtin"},
            ),
            patch("beddel.tools.kits.discover_kits", return_value=discovery),
            patch(
                "beddel.tools.kits.load_kit",
                return_value={"read_file": lambda: "kit"},
            ),
            pytest.warns(DeprecationWarning, match="shadows"),
        ):
            _build_tool_registry(workflow, {})


# ---------------------------------------------------------------------------
# AC #6: Strict mode raises KitManifestError on collision
# ---------------------------------------------------------------------------


class TestStrictMode:
    """BEDDEL_KIT_STRICT=true raises on ambiguous unnamespaced references."""

    def test_strict_raises_on_collision(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from beddel.cli.commands import _build_tool_registry

        monkeypatch.setenv("BEDDEL_KIT_STRICT", "true")

        workflow = MagicMock()
        workflow.metadata = {}

        kit_a = _make_manifest(
            name="kit-a",
            tools=[KitToolDeclaration(name="collided", target="json:dumps")],
        )
        kit_b = _make_manifest(
            name="kit-b",
            tools=[KitToolDeclaration(name="collided", target="json:loads")],
        )
        collision = KitCollision(tool_name="collided", kit_names=["kit-a", "kit-b"])
        discovery = KitDiscoveryResult(manifests=[kit_a, kit_b], collisions=[collision])

        with (
            patch("beddel.tools.discover_builtin_tools", return_value={}),
            patch("beddel.tools.kits.discover_kits", return_value=discovery),
            patch(
                "beddel.tools.kits.load_kit",
                return_value={"collided": lambda: "kit"},
            ),
            pytest.raises(KitManifestError) as exc_info,
        ):
            _build_tool_registry(workflow, {})

        assert exc_info.value.code == KIT_RESOLUTION_AMBIGUOUS
        assert "collided" in exc_info.value.message

    def test_strict_no_collision_does_not_raise(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from beddel.cli.commands import _build_tool_registry

        monkeypatch.setenv("BEDDEL_KIT_STRICT", "true")

        workflow = MagicMock()
        workflow.metadata = {}

        kit_manifest = _make_manifest(
            name="safe-kit",
            tools=[KitToolDeclaration(name="unique_tool", target="json:dumps")],
        )
        discovery = KitDiscoveryResult(manifests=[kit_manifest], collisions=[])

        with (
            patch("beddel.tools.discover_builtin_tools", return_value={}),
            patch("beddel.tools.kits.discover_kits", return_value=discovery),
            patch(
                "beddel.tools.kits.load_kit",
                return_value={"unique_tool": lambda: "kit"},
            ),
        ):
            result = _build_tool_registry(workflow, {})

        assert "unique_tool" in result
