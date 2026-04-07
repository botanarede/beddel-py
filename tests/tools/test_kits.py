"""Unit tests for beddel.tools.kits — discover_kits() and load_kit()."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import yaml

from beddel.domain.errors import KitDependencyError, KitManifestError
from beddel.domain.kit import (
    KitDiscoveryResult,
    KitManifest,
    KitToolDeclaration,
    SolutionKit,
    parse_kit_manifest,
)
from beddel.error_codes import KIT_LOAD_FAILED
from beddel.tools.kits import discover_kits, load_kit, load_kit_adapters

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_kit_yaml(kit_dir: Path, data: dict[str, Any]) -> Path:
    """Create a kit directory with a kit.yaml file and return the dir."""
    kit_dir.mkdir(parents=True, exist_ok=True)
    (kit_dir / "kit.yaml").write_text(yaml.dump(data), encoding="utf-8")
    return kit_dir


def _minimal_kit(name: str, *, tools: list[dict[str, str]] | None = None) -> dict[str, Any]:
    """Return a minimal valid kit manifest dict."""
    d: dict[str, Any] = {
        "name": name,
        "version": "0.1.0",
        "description": f"Test kit {name}",
    }
    if tools:
        d["tools"] = tools
    return d


def _make_manifest(
    name: str = "test-kit",
    tools: list[KitToolDeclaration] | None = None,
    targets: dict[str, Any] | None = None,
) -> KitManifest:
    """Build a KitManifest directly (no YAML file needed)."""
    from datetime import UTC, datetime

    kit = SolutionKit(
        name=name,
        version="0.1.0",
        description=f"Test kit {name}",
        tools=tools or [],
        targets=targets or {},
    )
    return KitManifest(
        kit=kit,
        root_path=Path("/fake/kit"),
        loaded_at=datetime.now(tz=UTC),
    )


# ---------------------------------------------------------------------------
# discover_kits — valid directories
# ---------------------------------------------------------------------------


class TestDiscoverKitsValid:
    """Tests for discover_kits() with valid kit directories."""

    def test_discovers_kits_from_single_path(self, tmp_path: Path) -> None:
        _write_kit_yaml(tmp_path / "alpha-kit", _minimal_kit("alpha-kit"))
        _write_kit_yaml(tmp_path / "beta-kit", _minimal_kit("beta-kit"))

        result = discover_kits([tmp_path])

        assert isinstance(result, KitDiscoveryResult)
        assert len(result.manifests) == 2
        names = [m.kit.name for m in result.manifests]
        assert "alpha-kit" in names
        assert "beta-kit" in names

    def test_alphabetical_ordering_by_kit_name(self, tmp_path: Path) -> None:
        _write_kit_yaml(tmp_path / "zulu-kit", _minimal_kit("zulu-kit"))
        _write_kit_yaml(tmp_path / "alpha-kit", _minimal_kit("alpha-kit"))
        _write_kit_yaml(tmp_path / "mike-kit", _minimal_kit("mike-kit"))

        result = discover_kits([tmp_path])

        names = [m.kit.name for m in result.manifests]
        assert names == ["alpha-kit", "mike-kit", "zulu-kit"]

    def test_project_local_before_user_global(self, tmp_path: Path) -> None:
        local = tmp_path / "local"
        global_ = tmp_path / "global"
        _write_kit_yaml(local / "aaa-kit", _minimal_kit("aaa-kit"))
        _write_kit_yaml(global_ / "bbb-kit", _minimal_kit("bbb-kit"))

        result = discover_kits([local, global_])

        names = [m.kit.name for m in result.manifests]
        # Alphabetical sort: aaa < bbb, and local is scanned first
        assert names == ["aaa-kit", "bbb-kit"]

    def test_discovers_from_multiple_paths(self, tmp_path: Path) -> None:
        path_a = tmp_path / "a"
        path_b = tmp_path / "b"
        _write_kit_yaml(path_a / "kit-one", _minimal_kit("kit-one"))
        _write_kit_yaml(path_b / "kit-two", _minimal_kit("kit-two"))

        result = discover_kits([path_a, path_b])

        assert len(result.manifests) == 2


# ---------------------------------------------------------------------------
# discover_kits — 3-path discovery with bundled kits
# ---------------------------------------------------------------------------


class TestDiscoverKitsBundled:
    """Tests for 3-path discovery: bundled → local → global."""

    def test_bundled_path_included_by_default(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When BEDDEL_KIT_PATHS is NOT set, BUNDLED_KITS_PATH is the first default."""
        bundled = tmp_path / "bundled"
        _write_kit_yaml(bundled / "bundled-kit", _minimal_kit("bundled-kit"))

        monkeypatch.delenv("BEDDEL_KIT_PATHS", raising=False)
        monkeypatch.setattr("beddel.tools.kits.BUNDLED_KITS_PATH", bundled)
        # Patch home and cwd to avoid scanning real ~/.beddel/kits/ and ./kits/
        monkeypatch.setattr(Path, "home", lambda: tmp_path / "fakehome")
        fakecwd = tmp_path / "fakecwd"
        fakecwd.mkdir()
        monkeypatch.chdir(fakecwd)

        result = discover_kits()

        assert len(result.manifests) == 1
        assert result.manifests[0].kit.name == "bundled-kit"
        assert result.manifests[0].source == "bundled"

    def test_local_overrides_bundled_same_name(self, tmp_path: Path) -> None:
        """A local kit with the same name as a bundled kit wins (later path)."""
        bundled = tmp_path / "bundled"
        local = tmp_path / "local"
        _write_kit_yaml(
            bundled / "shared-kit",
            _minimal_kit("shared-kit"),
        )
        _write_kit_yaml(
            local / "shared-kit",
            {**_minimal_kit("shared-kit"), "description": "local version"},
        )

        result = discover_kits([bundled, local])

        assert len(result.manifests) == 1
        assert result.manifests[0].kit.name == "shared-kit"
        # Later path (local) wins
        assert result.manifests[0].kit.description == "local version"
        assert result.manifests[0].source == "local"

    def test_global_overrides_local_and_bundled(self, tmp_path: Path) -> None:
        """Global path (index 2) overrides both bundled (0) and local (1)."""
        bundled = tmp_path / "bundled"
        local = tmp_path / "local"
        global_ = tmp_path / "global"
        _write_kit_yaml(bundled / "shared-kit", _minimal_kit("shared-kit"))
        _write_kit_yaml(local / "shared-kit", _minimal_kit("shared-kit"))
        _write_kit_yaml(
            global_ / "shared-kit",
            {**_minimal_kit("shared-kit"), "description": "global version"},
        )

        result = discover_kits([bundled, local, global_])

        assert len(result.manifests) == 1
        assert result.manifests[0].kit.description == "global version"
        assert result.manifests[0].source == "global"

    def test_env_var_replaces_all_defaults(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """BEDDEL_KIT_PATHS replaces all 3 default paths; kits get source='custom'."""
        custom = tmp_path / "custom"
        _write_kit_yaml(custom / "custom-kit", _minimal_kit("custom-kit"))
        monkeypatch.setenv("BEDDEL_KIT_PATHS", str(custom))

        result = discover_kits()

        assert len(result.manifests) == 1
        assert result.manifests[0].kit.name == "custom-kit"
        assert result.manifests[0].source == "custom"


# ---------------------------------------------------------------------------
# parse_kit_manifest — source field values
# ---------------------------------------------------------------------------


class TestKitManifestSource:
    """Tests for KitManifest.source field set by parse_kit_manifest()."""

    def test_source_bundled(self, tmp_path: Path) -> None:
        kit_dir = _write_kit_yaml(tmp_path / "my-kit", _minimal_kit("my-kit"))
        manifest = parse_kit_manifest(kit_dir / "kit.yaml", source="bundled")
        assert manifest.source == "bundled"

    def test_source_global(self, tmp_path: Path) -> None:
        kit_dir = _write_kit_yaml(tmp_path / "my-kit", _minimal_kit("my-kit"))
        manifest = parse_kit_manifest(kit_dir / "kit.yaml", source="global")
        assert manifest.source == "global"

    def test_source_defaults_to_local(self, tmp_path: Path) -> None:
        kit_dir = _write_kit_yaml(tmp_path / "my-kit", _minimal_kit("my-kit"))
        manifest = parse_kit_manifest(kit_dir / "kit.yaml")
        assert manifest.source == "local"

    def test_source_custom(self, tmp_path: Path) -> None:
        kit_dir = _write_kit_yaml(tmp_path / "my-kit", _minimal_kit("my-kit"))
        manifest = parse_kit_manifest(kit_dir / "kit.yaml", source="custom")
        assert manifest.source == "custom"


# ---------------------------------------------------------------------------
# Graceful degradation — missing deps
# ---------------------------------------------------------------------------


class TestGracefulDegradation:
    """Tests that _build_tool_registry() gracefully skips kits with missing deps."""

    def test_missing_deps_logs_warning_and_continues(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Kit with missing deps is skipped with BEDDEL-KIT-658 warning."""
        from beddel.cli.commands import _build_tool_registry

        workflow = MagicMock()
        workflow.metadata = {}

        good_manifest = _make_manifest(
            name="good-kit",
            tools=[KitToolDeclaration(name="good-tool", target="json:dumps")],
        )
        bad_manifest = _make_manifest(
            name="bad-kit",
            tools=[KitToolDeclaration(name="bad-tool", target="json:loads")],
        )
        discovery = KitDiscoveryResult(manifests=[bad_manifest, good_manifest], collisions=[])

        def _selective_load(manifest: KitManifest) -> dict[str, Callable[..., Any]]:
            if manifest.kit.name == "bad-kit":
                raise KitDependencyError(
                    code="BEDDEL-KIT-653",
                    message="missing deps",
                    missing_packages=["some-pkg"],
                )
            return {"good-tool": lambda: "ok"}

        with (
            patch("beddel.tools.kits.discover_kits", return_value=discovery),
            patch("beddel.tools.kits.load_kit", side_effect=_selective_load),
            caplog.at_level(logging.WARNING),
        ):
            result = _build_tool_registry(workflow, {})

        # Good kit's tool is present
        assert "good-tool" in result
        # Bad kit's tool is NOT present
        assert "bad-tool" not in result
        # Warning logged with BEDDEL-KIT-658
        assert any("BEDDEL-KIT-658" in msg for msg in caplog.messages)


# ---------------------------------------------------------------------------
# discover_kits — empty / missing directories
# ---------------------------------------------------------------------------


class TestDiscoverKitsEmpty:
    """Tests for discover_kits() with empty or missing directories."""

    def test_empty_directory_returns_empty_list(self, tmp_path: Path) -> None:
        empty = tmp_path / "empty"
        empty.mkdir()

        result = discover_kits([empty])

        assert result.manifests == []
        assert result.collisions == []

    def test_missing_directory_returns_empty_list(self, tmp_path: Path) -> None:
        result = discover_kits([tmp_path / "nonexistent"])

        assert result.manifests == []
        assert result.collisions == []

    def test_no_kit_yaml_in_subdirs_returns_empty(self, tmp_path: Path) -> None:
        (tmp_path / "some-dir").mkdir()
        (tmp_path / "some-dir" / "README.md").write_text("hi")

        result = discover_kits([tmp_path])

        assert result.manifests == []
        assert result.collisions == []


# ---------------------------------------------------------------------------
# discover_kits — BEDDEL_KIT_PATHS env var override
# ---------------------------------------------------------------------------


class TestDiscoverKitsEnvVar:
    """Tests for discover_kits() with BEDDEL_KIT_PATHS env var."""

    def test_env_var_overrides_defaults(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        custom = tmp_path / "custom"
        _write_kit_yaml(custom / "env-kit", _minimal_kit("env-kit"))
        monkeypatch.setenv("BEDDEL_KIT_PATHS", str(custom))

        result = discover_kits()  # paths=None → reads env var

        assert len(result.manifests) == 1
        assert result.manifests[0].kit.name == "env-kit"

    def test_env_var_colon_separated(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        path_a = tmp_path / "a"
        path_b = tmp_path / "b"
        _write_kit_yaml(path_a / "kit-a", _minimal_kit("kit-a"))
        _write_kit_yaml(path_b / "kit-b", _minimal_kit("kit-b"))
        monkeypatch.setenv("BEDDEL_KIT_PATHS", f"{path_a}:{path_b}")

        result = discover_kits()

        assert len(result.manifests) == 2

    def test_env_var_empty_string_uses_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("BEDDEL_KIT_PATHS", "")

        # Empty env var → falls through to defaults (which likely don't exist)
        result = discover_kits()

        assert isinstance(result, KitDiscoveryResult)


# ---------------------------------------------------------------------------
# discover_kits — fail-open on invalid manifests
# ---------------------------------------------------------------------------


class TestDiscoverKitsFailOpen:
    """Tests that discover_kits() skips invalid manifests (fail-open)."""

    def test_invalid_manifest_skipped_others_returned(self, tmp_path: Path) -> None:
        # Valid kit
        _write_kit_yaml(tmp_path / "good-kit", _minimal_kit("good-kit"))
        # Invalid kit (missing required fields)
        bad_dir = tmp_path / "bad-kit"
        bad_dir.mkdir()
        (bad_dir / "kit.yaml").write_text("not: valid\nkit: yaml", encoding="utf-8")

        result = discover_kits([tmp_path])

        assert len(result.manifests) == 1
        assert result.manifests[0].kit.name == "good-kit"

    def test_all_invalid_returns_empty(self, tmp_path: Path) -> None:
        bad_dir = tmp_path / "bad-kit"
        bad_dir.mkdir()
        (bad_dir / "kit.yaml").write_text("garbage: true", encoding="utf-8")

        result = discover_kits([tmp_path])

        assert result.manifests == []


# ---------------------------------------------------------------------------
# load_kit — valid tool declarations
# ---------------------------------------------------------------------------


class TestLoadKitValid:
    """Tests for load_kit() with valid tool declarations."""

    def test_loads_stdlib_function(self) -> None:
        manifest = _make_manifest(tools=[KitToolDeclaration(name="dumps", target="json:dumps")])

        result = load_kit(manifest)

        assert "dumps" in result
        assert callable(result["dumps"])
        import json

        assert result["dumps"] is json.dumps

    def test_loads_os_path_function(self) -> None:
        manifest = _make_manifest(
            tools=[KitToolDeclaration(name="exists", target="os.path:exists")]
        )

        result = load_kit(manifest)

        assert "exists" in result
        import os.path

        assert result["exists"] is os.path.exists

    def test_loads_multiple_tools(self) -> None:
        manifest = _make_manifest(
            tools=[
                KitToolDeclaration(name="dumps", target="json:dumps"),
                KitToolDeclaration(name="loads", target="json:loads"),
            ]
        )

        result = load_kit(manifest)

        assert len(result) == 2
        assert "dumps" in result
        assert "loads" in result

    def test_empty_tools_returns_empty_dict(self) -> None:
        manifest = _make_manifest(tools=[])

        result = load_kit(manifest)

        assert result == {}


# ---------------------------------------------------------------------------
# load_kit — error cases
# ---------------------------------------------------------------------------


class TestLoadKitErrors:
    """Tests for load_kit() error handling."""

    def test_bad_module_raises_kit_manifest_error(self) -> None:
        manifest = _make_manifest(
            tools=[KitToolDeclaration(name="bad", target="nonexistent_module_xyz:func")]
        )

        with pytest.raises(KitManifestError) as exc_info:
            load_kit(manifest)

        assert exc_info.value.code == KIT_LOAD_FAILED
        assert exc_info.value.code == "BEDDEL-KIT-652"

    def test_missing_function_raises_kit_manifest_error(self) -> None:
        manifest = _make_manifest(
            tools=[KitToolDeclaration(name="bad", target="json:nonexistent_function_xyz")]
        )

        with pytest.raises(KitManifestError) as exc_info:
            load_kit(manifest)

        assert exc_info.value.code == KIT_LOAD_FAILED
        assert exc_info.value.code == "BEDDEL-KIT-652"

    def test_missing_colon_raises_kit_manifest_error(self) -> None:
        manifest = _make_manifest(tools=[KitToolDeclaration(name="bad", target="json.dumps")])

        with pytest.raises(KitManifestError) as exc_info:
            load_kit(manifest)

        assert exc_info.value.code == KIT_LOAD_FAILED
        assert exc_info.value.code == "BEDDEL-KIT-652"

    def test_error_details_contain_kit_and_tool_info(self) -> None:
        manifest = _make_manifest(
            name="my-kit",
            tools=[KitToolDeclaration(name="bad-tool", target="nope_mod:nope_fn")],
        )

        with pytest.raises(KitManifestError) as exc_info:
            load_kit(manifest)

        assert exc_info.value.details["kit"] == "my-kit"
        assert exc_info.value.details["tool"] == "bad-tool"


# ---------------------------------------------------------------------------
# _build_tool_registry — 4-layer merge order
# ---------------------------------------------------------------------------


class TestBuildToolRegistry:
    """Tests for _build_tool_registry() 3-layer merge order."""

    def test_three_layer_merge_order(self) -> None:
        from beddel.cli.commands import _build_tool_registry

        # Create a mock workflow with inline tools
        workflow = MagicMock()
        workflow.metadata = {
            "_inline_tools": {"shared": lambda: "inline", "inline-only": lambda: "y"},
        }

        # CLI tools override everything
        cli_tools: dict[str, Callable[..., Any]] = {
            "shared": lambda: "cli",
            "cli-only": lambda: "y",
        }

        # Mock kit tools
        kit_manifest = _make_manifest(
            name="test-kit",
            tools=[KitToolDeclaration(name="shared", target="json:dumps")],
        )
        discovery_result = KitDiscoveryResult(manifests=[kit_manifest], collisions=[])

        with (
            patch(
                "beddel.tools.kits.discover_kits",
                return_value=discovery_result,
            ),
            patch(
                "beddel.tools.kits.load_kit",
                return_value={"shared": lambda: "kit", "kit-only": lambda: "y"},
            ),
        ):
            result = _build_tool_registry(workflow, cli_tools)

        # CLI flags win over everything
        assert result["shared"]() == "cli"
        # All layers contribute unique tools
        assert "kit-only" in result
        assert "inline-only" in result
        assert "cli-only" in result

    def test_inline_overrides_kit(self) -> None:
        from beddel.cli.commands import _build_tool_registry

        workflow = MagicMock()
        workflow.metadata = {
            "_inline_tools": {"tool-x": lambda: "inline"},
        }

        kit_manifest = _make_manifest(
            tools=[KitToolDeclaration(name="tool-x", target="json:dumps")],
        )
        discovery_result = KitDiscoveryResult(manifests=[kit_manifest], collisions=[])

        with (
            patch(
                "beddel.tools.kits.discover_kits",
                return_value=discovery_result,
            ),
            patch(
                "beddel.tools.kits.load_kit",
                return_value={"tool-x": lambda: "kit"},
            ),
        ):
            result = _build_tool_registry(workflow, {})

        assert result["tool-x"]() == "inline"

    def test_kit_tools_are_layer_1(self) -> None:
        """Kit tools appear in registry as the base layer."""
        from beddel.cli.commands import _build_tool_registry

        workflow = MagicMock()
        workflow.metadata = {}

        kit_manifest = _make_manifest(
            tools=[KitToolDeclaration(name="tool-x", target="json:dumps")],
        )
        discovery_result = KitDiscoveryResult(manifests=[kit_manifest], collisions=[])

        with (
            patch(
                "beddel.tools.kits.discover_kits",
                return_value=discovery_result,
            ),
            patch(
                "beddel.tools.kits.load_kit",
                return_value={"tool-x": lambda: "kit"},
            ),
        ):
            result = _build_tool_registry(workflow, {})

        assert result["tool-x"]() == "kit"


# ---------------------------------------------------------------------------
# --no-kits disables kit loading
# ---------------------------------------------------------------------------


class TestNoKitsFlag:
    """Tests that --no-kits disables kit discovery."""

    def test_no_kits_skips_discover_kits(self) -> None:
        from beddel.cli.commands import _build_tool_registry

        workflow = MagicMock()
        workflow.metadata = {}

        with (
            patch(
                "beddel.tools.kits.discover_kits",
            ) as mock_discover,
        ):
            _build_tool_registry(workflow, {}, no_kits=True)

        mock_discover.assert_not_called()

    def test_no_kits_still_includes_inline_and_cli(self) -> None:
        from beddel.cli.commands import _build_tool_registry

        workflow = MagicMock()
        workflow.metadata = {"_inline_tools": {"inline": lambda: "y"}}

        cli_tools: dict[str, Callable[..., Any]] = {"cli": lambda: "y"}

        result = _build_tool_registry(workflow, cli_tools, no_kits=True)

        assert "inline" in result
        assert "cli" in result


# ---------------------------------------------------------------------------
# load_kit_adapters — adapter resolution from targets.python
# ---------------------------------------------------------------------------


class TestLoadKitAdapters:
    """Tests for load_kit_adapters() — AC #1, #6, #10."""

    @staticmethod
    def _make_adapter_manifest(
        name: str = "adapter-kit",
        adapters: list[dict[str, Any]] | None = None,
        dependencies: list[str] | None = None,
        *,
        include_targets: bool = True,
    ) -> KitManifest:
        """Build a KitManifest with targets.python.adapters populated."""
        targets: dict[str, Any] = {}
        if include_targets and adapters is not None:
            python_block: dict[str, Any] = {
                "module": "fake_kit",
                "adapters": adapters,
            }
            if dependencies is not None:
                python_block["dependencies"] = dependencies
            targets["python"] = python_block
        return _make_manifest(name=name, targets=targets)

    def test_loads_adapter_from_targets_python(self) -> None:
        """AC #1: importlib resolves adapter class and instantiates it."""

        class _FakeAgentAdapter:
            pass

        fake_module = MagicMock()
        fake_module.FakeAgentAdapter = _FakeAgentAdapter

        manifest = self._make_adapter_manifest(
            adapters=[
                {
                    "name": "my-adapter",
                    "target": "fake_kit.adapters:FakeAgentAdapter",
                    "port": "IAgentAdapter",
                },
            ],
        )

        with patch("importlib.import_module", return_value=fake_module) as mock_import:
            result = load_kit_adapters(manifest)

        mock_import.assert_called_once_with("fake_kit.adapters")
        assert ("IAgentAdapter", "my-adapter") in result
        assert isinstance(result[("IAgentAdapter", "my-adapter")], _FakeAgentAdapter)

    def test_missing_name_raises_kit_manifest_error(self) -> None:
        """AC #6: adapter without name field raises KitManifestError."""

        manifest = self._make_adapter_manifest(
            adapters=[
                {
                    "implementation": "SomeAdapter",
                    "port": "IAgentAdapter",
                },
            ],
        )

        with pytest.raises(KitManifestError) as exc_info:
            load_kit_adapters(manifest)

        assert exc_info.value.code == KIT_LOAD_FAILED
        assert "name" in exc_info.value.message.lower()

    def test_missing_target_raises_kit_manifest_error(self) -> None:
        """AC #6: adapter without target field raises KitManifestError."""

        manifest = self._make_adapter_manifest(
            adapters=[
                {
                    "name": "no-target-adapter",
                    "implementation": "SomeAdapter",
                    "port": "IAgentAdapter",
                },
            ],
        )

        with pytest.raises(KitManifestError) as exc_info:
            load_kit_adapters(manifest)

        assert exc_info.value.code == KIT_LOAD_FAILED
        assert "target" in exc_info.value.message.lower()

    def test_missing_deps_raises_kit_dependency_error(self) -> None:
        """AC #10: missing dependencies raise KitDependencyError."""

        manifest = self._make_adapter_manifest(
            adapters=[
                {
                    "name": "dep-adapter",
                    "target": "some_pkg.mod:Cls",
                    "port": "IAgentAdapter",
                },
            ],
            dependencies=["nonexistent-pkg-xyz>=1.0"],
        )

        with pytest.raises(KitDependencyError) as exc_info:
            load_kit_adapters(manifest)

        assert exc_info.value.code == "BEDDEL-KIT-653"
        assert "nonexistent-pkg-xyz>=1.0" in exc_info.value.missing_packages

    def test_empty_adapters_returns_empty_dict(self) -> None:
        """Kit with empty adapters list returns {}."""

        manifest = self._make_adapter_manifest(adapters=[])

        result = load_kit_adapters(manifest)

        assert result == {}

    def test_no_targets_python_returns_empty_dict(self) -> None:
        """Kit without targets.python section returns {}."""

        manifest = self._make_adapter_manifest(include_targets=False)

        result = load_kit_adapters(manifest)

        assert result == {}
