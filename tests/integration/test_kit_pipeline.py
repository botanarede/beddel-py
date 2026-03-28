"""End-to-end integration tests for the kit pipeline.

Validates the full kit lifecycle: discover → parse → load → register → invoke.
Uses ``tmp_path`` and stdlib targets to avoid CWD or subprocess dependencies.
"""

from __future__ import annotations

import json
from datetime import UTC
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import yaml

from beddel.domain.kit import (
    KitDiscoveryResult,
    KitManifest,
    KitToolDeclaration,
    SolutionKit,
    parse_kit_manifest,
)
from beddel.tools.kits import discover_kits, load_kit

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_kit_yaml(kit_dir: Path, data: dict[str, Any]) -> Path:
    """Create a kit directory with a kit.yaml and return the dir."""
    kit_dir.mkdir(parents=True, exist_ok=True)
    (kit_dir / "kit.yaml").write_text(yaml.dump(data), encoding="utf-8")
    return kit_dir


def _reference_kit_data() -> dict[str, Any]:
    """Return a dict matching the reference software-development-kit manifest."""
    return {
        "name": "software-development-kit",
        "version": "0.1.0",
        "description": "Development workflow tools — validation gates and epic creation",
        "author": "Beddel Team",
        "tools": [
            {
                "name": "pytest_gate",
                "target": "kits.software_development_kit.tools.gates:pytest_gate",
                "description": "Run pytest with fail-on-error",
                "category": "gates",
            },
            {
                "name": "ruff_check_gate",
                "target": "kits.software_development_kit.tools.gates:ruff_check_gate",
                "description": "Run ruff linter",
                "category": "gates",
            },
            {
                "name": "ruff_format_gate",
                "target": "kits.software_development_kit.tools.gates:ruff_format_gate",
                "description": "Run ruff formatter check",
                "category": "gates",
            },
            {
                "name": "mypy_gate",
                "target": "kits.software_development_kit.tools.gates:mypy_gate",
                "description": "Run mypy type checker",
                "category": "gates",
            },
        ],
        "workflows": [
            {
                "name": "create-epic",
                "path": "workflows/create-epic.yaml",
                "description": "Create epic scaffolding (directories, template files)",
            },
        ],
    }


def _stdlib_kit_data(name: str = "stdlib-kit") -> dict[str, Any]:
    """Return a kit manifest using stdlib targets (importable in tests)."""
    return {
        "name": name,
        "version": "0.1.0",
        "description": "Kit with stdlib tool targets",
        "tools": [
            {"name": "dumps", "target": "json:dumps", "category": "util"},
            {"name": "exists", "target": "os.path:exists", "category": "util"},
        ],
    }


def _make_manifest(
    name: str = "test-kit",
    tools: list[KitToolDeclaration] | None = None,
) -> KitManifest:
    """Build a KitManifest directly (no YAML file needed)."""
    from datetime import datetime

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
# 1. discover_kits finds the reference kit
# ---------------------------------------------------------------------------


class TestDiscoverKitsFindsReferenceKit:
    """discover_kits() locates a kit directory with a valid kit.yaml."""

    def test_discovers_kit_in_tmp_path(self, tmp_path: Path) -> None:
        _write_kit_yaml(tmp_path / "software-development-kit", _reference_kit_data())

        result = discover_kits([tmp_path])

        assert isinstance(result, KitDiscoveryResult)
        assert len(result.manifests) == 1
        assert result.manifests[0].kit.name == "software-development-kit"

    def test_discovers_multiple_kits(self, tmp_path: Path) -> None:
        _write_kit_yaml(tmp_path / "software-development-kit", _reference_kit_data())
        _write_kit_yaml(tmp_path / "stdlib-kit", _stdlib_kit_data())

        result = discover_kits([tmp_path])

        names = [m.kit.name for m in result.manifests]
        assert "software-development-kit" in names
        assert "stdlib-kit" in names
        assert len(result.manifests) == 2


# ---------------------------------------------------------------------------
# 2. parse_kit_manifest on the reference kit
# ---------------------------------------------------------------------------


class TestParseKitManifestReferenceKit:
    """parse_kit_manifest() correctly parses the reference kit structure."""

    def test_all_fields_parsed(self, tmp_path: Path) -> None:
        kit_dir = _write_kit_yaml(tmp_path / "sdk", _reference_kit_data())
        manifest_path = kit_dir / "kit.yaml"

        manifest = parse_kit_manifest(manifest_path)

        assert manifest.kit.name == "software-development-kit"
        assert manifest.kit.version == "0.1.0"
        assert manifest.kit.author == "Beddel Team"
        assert "validation gates" in manifest.kit.description

    def test_tools_parsed(self, tmp_path: Path) -> None:
        kit_dir = _write_kit_yaml(tmp_path / "sdk", _reference_kit_data())

        manifest = parse_kit_manifest(kit_dir / "kit.yaml")

        tool_names = [t.name for t in manifest.kit.tools]
        assert tool_names == [
            "pytest_gate",
            "ruff_check_gate",
            "ruff_format_gate",
            "mypy_gate",
        ]
        # Verify target format
        for tool in manifest.kit.tools:
            assert ":" in tool.target
            assert tool.category == "gates"

    def test_workflows_parsed(self, tmp_path: Path) -> None:
        kit_dir = _write_kit_yaml(tmp_path / "sdk", _reference_kit_data())

        manifest = parse_kit_manifest(kit_dir / "kit.yaml")

        assert len(manifest.kit.workflows) == 1
        assert manifest.kit.workflows[0].name == "create-epic"
        assert manifest.kit.workflows[0].path == "workflows/create-epic.yaml"

    def test_root_path_and_loaded_at(self, tmp_path: Path) -> None:
        kit_dir = _write_kit_yaml(tmp_path / "sdk", _reference_kit_data())

        manifest = parse_kit_manifest(kit_dir / "kit.yaml")

        assert manifest.root_path == kit_dir.resolve()
        assert manifest.loaded_at.tzinfo is not None


# ---------------------------------------------------------------------------
# 3. load_kit resolves tools to callables
# ---------------------------------------------------------------------------


class TestLoadKitResolvesCallables:
    """load_kit() resolves tool targets to callable functions."""

    def test_stdlib_tools_are_callable(self) -> None:
        manifest = _make_manifest(
            tools=[
                KitToolDeclaration(name="dumps", target="json:dumps"),
                KitToolDeclaration(name="exists", target="os.path:exists"),
            ],
        )

        tools = load_kit(manifest)

        assert callable(tools["dumps"])
        assert callable(tools["exists"])
        assert tools["dumps"] is json.dumps
        import os.path

        assert tools["exists"] is os.path.exists

    def test_loaded_tool_count_matches_declarations(self) -> None:
        manifest = _make_manifest(
            tools=[
                KitToolDeclaration(name="dumps", target="json:dumps"),
                KitToolDeclaration(name="loads", target="json:loads"),
            ],
        )

        tools = load_kit(manifest)

        assert len(tools) == 2


# ---------------------------------------------------------------------------
# 4. Namespace registration via _build_tool_registry
# ---------------------------------------------------------------------------


class TestNamespaceRegistration:
    """_build_tool_registry registers both namespaced and unnamespaced keys."""

    def test_both_namespaced_and_unnamespaced_keys(self) -> None:
        from beddel.cli.commands import _build_tool_registry

        workflow = MagicMock()
        workflow.metadata = {}

        kit_manifest = _make_manifest(
            name="my-kit",
            tools=[KitToolDeclaration(name="my_tool", target="json:dumps")],
        )
        discovery_result = KitDiscoveryResult(manifests=[kit_manifest], collisions=[])

        with (
            patch(
                "beddel.tools.discover_builtin_tools",
                return_value={},
            ),
            patch(
                "beddel.tools.kits.discover_kits",
                return_value=discovery_result,
            ),
            patch(
                "beddel.tools.kits.load_kit",
                return_value={"my_tool": json.dumps},
            ),
        ):
            result = _build_tool_registry(workflow, {})

        # Namespaced form: {kit_name}:{tool_name}
        assert "my-kit:my_tool" in result
        # Unnamespaced form: {tool_name}
        assert "my_tool" in result
        # Both point to the same callable
        assert result["my-kit:my_tool"] is json.dumps
        assert result["my_tool"] is json.dumps


# ---------------------------------------------------------------------------
# 5. Invoke a loaded tool
# ---------------------------------------------------------------------------


class TestInvokeLoadedTool:
    """Load a tool via load_kit() and invoke it to verify the result."""

    def test_invoke_json_dumps(self) -> None:
        manifest = _make_manifest(
            tools=[KitToolDeclaration(name="dumps", target="json:dumps")],
        )

        tools = load_kit(manifest)
        result = tools["dumps"]({"key": "value"})

        assert result == '{"key": "value"}'

    def test_invoke_json_loads(self) -> None:
        manifest = _make_manifest(
            tools=[KitToolDeclaration(name="loads", target="json:loads")],
        )

        tools = load_kit(manifest)
        result = tools["loads"]('{"a": 1}')

        assert result == {"a": 1}

    def test_invoke_os_path_exists(self, tmp_path: Path) -> None:
        manifest = _make_manifest(
            tools=[KitToolDeclaration(name="exists", target="os.path:exists")],
        )

        tools = load_kit(manifest)

        assert tools["exists"](str(tmp_path)) is True
        assert tools["exists"](str(tmp_path / "nonexistent")) is False
