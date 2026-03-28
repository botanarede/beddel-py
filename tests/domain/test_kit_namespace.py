"""Unit tests for kit namespace registration, collision detection, and namespace-aware lookup."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import yaml

from beddel.cli.commands import _build_tool_registry
from beddel.domain.errors import PrimitiveError
from beddel.domain.kit import (
    KitCollision,
    KitDiscoveryResult,
    KitManifest,
    KitToolDeclaration,
    SolutionKit,
)
from beddel.primitives.tool import ToolPrimitive

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_manifest(
    name: str = "test-kit",
    tools: list[KitToolDeclaration] | None = None,
) -> KitManifest:
    """Build a KitManifest directly (no YAML file needed)."""
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


def _make_mock_workflow(inline_tools: dict[str, Any] | None = None) -> MagicMock:
    """Create a minimal mock workflow for _build_tool_registry."""
    wf = MagicMock()
    wf.metadata = {"_inline_tools": inline_tools or {}}
    return wf


def _make_mock_context(step_id: str = "step-1") -> MagicMock:
    """Create a minimal mock ExecutionContext for _check_allowlist."""
    ctx = MagicMock()
    ctx.current_step_id = step_id
    return ctx


def _write_kit_yaml(kit_dir: Path, data: dict[str, Any]) -> Path:
    """Create a kit directory with a kit.yaml file and return the dir."""
    kit_dir.mkdir(parents=True, exist_ok=True)
    (kit_dir / "kit.yaml").write_text(yaml.dump(data), encoding="utf-8")
    return kit_dir


def _minimal_kit(
    name: str,
    *,
    tools: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Return a minimal valid kit manifest dict."""
    d: dict[str, Any] = {
        "name": name,
        "version": "0.1.0",
        "description": f"Test kit {name}",
    }
    if tools:
        d["tools"] = tools
    return d


# ---------------------------------------------------------------------------
# 1. Namespaced registration
# ---------------------------------------------------------------------------


class TestNamespacedRegistration:
    """Verify both {kit_name}:{tool_name} and {tool_name} keys exist."""

    def test_namespaced_and_unnamespaced_keys_present(self) -> None:
        workflow = _make_mock_workflow()
        manifest = _make_manifest(
            name="my-kit",
            tools=[KitToolDeclaration(name="my_tool", target="json:dumps")],
        )
        discovery = KitDiscoveryResult(manifests=[manifest], collisions=[])

        with (
            patch("beddel.tools.discover_builtin_tools", return_value={}),
            patch("beddel.tools.kits.discover_kits", return_value=discovery),
            patch(
                "beddel.tools.kits.load_kit",
                return_value={"my_tool": lambda: "ok"},
            ),
        ):
            result = _build_tool_registry(workflow, {})

        assert "my-kit:my_tool" in result
        assert "my_tool" in result


# ---------------------------------------------------------------------------
# 2. Unnamespaced shortcut
# ---------------------------------------------------------------------------


class TestUnnamespacedShortcut:
    """When only one kit declares a tool name, unnamespaced form is present."""

    def test_single_kit_tool_has_unnamespaced_shortcut(self) -> None:
        workflow = _make_mock_workflow()
        manifest = _make_manifest(
            name="solo-kit",
            tools=[KitToolDeclaration(name="unique_tool", target="json:dumps")],
        )
        discovery = KitDiscoveryResult(manifests=[manifest], collisions=[])

        with (
            patch("beddel.tools.discover_builtin_tools", return_value={}),
            patch("beddel.tools.kits.discover_kits", return_value=discovery),
            patch(
                "beddel.tools.kits.load_kit",
                return_value={"unique_tool": lambda: "solo"},
            ),
        ):
            result = _build_tool_registry(workflow, {})

        assert "unique_tool" in result
        assert result["unique_tool"]() == "solo"


# ---------------------------------------------------------------------------
# 3. Collision detection
# ---------------------------------------------------------------------------


class TestCollisionDetection:
    """Two kits with the same tool name: only namespaced forms, warning logged."""

    def test_collision_removes_unnamespaced_form(self) -> None:
        workflow = _make_mock_workflow()
        manifest_a = _make_manifest(
            name="kit-a",
            tools=[KitToolDeclaration(name="shared_tool", target="json:dumps")],
        )
        manifest_b = _make_manifest(
            name="kit-b",
            tools=[KitToolDeclaration(name="shared_tool", target="json:loads")],
        )
        collision = KitCollision(
            tool_name="shared_tool",
            kit_names=["kit-a", "kit-b"],
        )
        discovery = KitDiscoveryResult(
            manifests=[manifest_a, manifest_b],
            collisions=[collision],
        )

        with (
            patch("beddel.tools.discover_builtin_tools", return_value={}),
            patch("beddel.tools.kits.discover_kits", return_value=discovery),
            patch(
                "beddel.tools.kits.load_kit",
                side_effect=[
                    {"shared_tool": lambda: "a"},
                    {"shared_tool": lambda: "b"},
                ],
            ),
        ):
            result = _build_tool_registry(workflow, {})

        # Both namespaced forms exist
        assert "kit-a:shared_tool" in result
        assert "kit-b:shared_tool" in result
        # Unnamespaced form does NOT exist
        assert "shared_tool" not in result

    def test_collision_logs_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        workflow = _make_mock_workflow()
        manifest_a = _make_manifest(
            name="kit-a",
            tools=[KitToolDeclaration(name="shared_tool", target="json:dumps")],
        )
        manifest_b = _make_manifest(
            name="kit-b",
            tools=[KitToolDeclaration(name="shared_tool", target="json:loads")],
        )
        collision = KitCollision(
            tool_name="shared_tool",
            kit_names=["kit-a", "kit-b"],
        )
        discovery = KitDiscoveryResult(
            manifests=[manifest_a, manifest_b],
            collisions=[collision],
        )

        with (
            caplog.at_level(logging.WARNING, logger="beddel.cli.commands"),
            patch("beddel.tools.discover_builtin_tools", return_value={}),
            patch("beddel.tools.kits.discover_kits", return_value=discovery),
            patch(
                "beddel.tools.kits.load_kit",
                side_effect=[
                    {"shared_tool": lambda: "a"},
                    {"shared_tool": lambda: "b"},
                ],
            ),
        ):
            _build_tool_registry(workflow, {})

        assert any("shared_tool" in r.message for r in caplog.records)
        assert any("collision" in r.message.lower() for r in caplog.records)


# ---------------------------------------------------------------------------
# 4. KitDiscoveryResult collisions via discover_kits()
# ---------------------------------------------------------------------------


class TestKitDiscoveryResultCollisions:
    """discover_kits() with overlapping tool names populates collisions."""

    def test_discover_kits_detects_collisions(self, tmp_path: Path) -> None:
        _write_kit_yaml(
            tmp_path / "kit-a",
            _minimal_kit(
                "kit-a",
                tools=[{"name": "overlap", "target": "json:dumps"}],
            ),
        )
        _write_kit_yaml(
            tmp_path / "kit-b",
            _minimal_kit(
                "kit-b",
                tools=[{"name": "overlap", "target": "json:loads"}],
            ),
        )

        from beddel.tools.kits import discover_kits

        result = discover_kits([tmp_path])

        assert len(result.collisions) == 1
        assert result.collisions[0].tool_name == "overlap"
        assert sorted(result.collisions[0].kit_names) == ["kit-a", "kit-b"]


# ---------------------------------------------------------------------------
# 5. _check_allowlist with namespaced tools
# ---------------------------------------------------------------------------


class TestCheckAllowlistNamespaced:
    """allowed_tools: ["my_tool"] permits both my_tool and some-kit:my_tool."""

    def test_unnamespaced_tool_allowed(self) -> None:
        ctx = _make_mock_context()
        # Should not raise
        ToolPrimitive._check_allowlist("my_tool", ["my_tool"], ctx)

    def test_namespaced_tool_allowed_via_base_name(self) -> None:
        ctx = _make_mock_context()
        # "some-kit:my_tool" should be allowed because "my_tool" is in the list
        ToolPrimitive._check_allowlist("some-kit:my_tool", ["my_tool"], ctx)

    def test_none_allowlist_permits_everything(self) -> None:
        ctx = _make_mock_context()
        # None means unrestricted
        ToolPrimitive._check_allowlist("any-kit:any_tool", None, ctx)


# ---------------------------------------------------------------------------
# 6. _check_allowlist blocks unknown namespaced tool
# ---------------------------------------------------------------------------


class TestCheckAllowlistBlocks:
    """allowed_tools: ["other_tool"] blocks some-kit:my_tool."""

    def test_namespaced_tool_blocked_when_base_not_in_allowlist(self) -> None:
        ctx = _make_mock_context()
        with pytest.raises(PrimitiveError) as exc_info:
            ToolPrimitive._check_allowlist(
                "some-kit:my_tool",
                ["other_tool"],
                ctx,
            )
        assert "not in the workflow allowed_tools" in exc_info.value.message

    def test_unnamespaced_tool_blocked_when_not_in_allowlist(self) -> None:
        ctx = _make_mock_context()
        with pytest.raises(PrimitiveError) as exc_info:
            ToolPrimitive._check_allowlist("my_tool", ["other_tool"], ctx)
        assert "not in the workflow allowed_tools" in exc_info.value.message
