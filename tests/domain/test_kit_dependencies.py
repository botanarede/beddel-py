"""Unit tests for kit dependency validation and SolutionKit model fields.

Covers:
- load_kit() dependency validation (AC #4): all deps installed, missing dep, no deps
- SolutionKit model with dependencies and targets fields (subtask 5.3)
- KitAdapterDeclaration reconciliation (subtask 5.4)
- Backward compatibility for kits without dependencies/targets (AC #7)
"""

from __future__ import annotations

from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from beddel.domain.errors import KitDependencyError
from beddel.domain.kit import (
    KitAdapterDeclaration,
    KitManifest,
    KitToolDeclaration,
    SolutionKit,
)
from beddel.error_codes import KIT_DEPENDENCY_MISSING
from beddel.tools.kits import load_kit

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_manifest(
    dependencies: list[str] | None = None,
    tools: list[KitToolDeclaration] | None = None,
) -> KitManifest:
    """Build a KitManifest with optional dependencies and tools."""
    kit = SolutionKit(
        name="test-kit",
        version="0.1.0",
        description="Test kit",
        dependencies=dependencies or [],
        tools=tools or [],
    )
    return KitManifest(
        kit=kit,
        root_path=Path("/tmp/test-kit"),
        loaded_at=datetime.now(UTC),
    )


# ---------------------------------------------------------------------------
# load_kit() — dependency validation (AC #4)
# ---------------------------------------------------------------------------


class TestLoadKitDependencyValidation:
    """Tests that load_kit() validates declared pip dependencies."""

    def test_all_deps_installed_passes(self) -> None:
        """When all declared dependencies are installed, load_kit succeeds."""
        manifest = _make_manifest(dependencies=["httpx>=0.27", "pydantic>=2.0"])

        with patch("beddel.tools.kits.distribution") as mock_dist:
            mock_dist.return_value = MagicMock()
            result = load_kit(manifest)

        assert result == {}

    def test_missing_dep_raises_kit_dependency_error(self) -> None:
        """When a dependency is missing, load_kit raises KitDependencyError."""
        manifest = _make_manifest(dependencies=["nonexistent-pkg>=1.0"])

        with patch("beddel.tools.kits.distribution") as mock_dist:
            mock_dist.side_effect = PackageNotFoundError("nonexistent-pkg")
            with pytest.raises(KitDependencyError) as exc_info:
                load_kit(manifest)

        assert exc_info.value.code == KIT_DEPENDENCY_MISSING
        assert "nonexistent-pkg>=1.0" in exc_info.value.missing_packages

    def test_missing_dep_error_message_contains_install_hint(self) -> None:
        """Error message includes pip install hint."""
        manifest = _make_manifest(dependencies=["missing-lib>=2.0"])

        with patch("beddel.tools.kits.distribution") as mock_dist:
            mock_dist.side_effect = PackageNotFoundError("missing-lib")
            with pytest.raises(KitDependencyError) as exc_info:
                load_kit(manifest)

        assert "pip install" in exc_info.value.message

    def test_multiple_deps_one_missing(self) -> None:
        """Only the missing dep appears in missing_packages."""
        manifest = _make_manifest(dependencies=["installed-pkg>=1.0", "missing-pkg>=2.0"])

        def _side_effect(name: str) -> MagicMock:
            if name == "missing-pkg":
                raise PackageNotFoundError("missing-pkg")
            return MagicMock()

        with (
            patch("beddel.tools.kits.distribution", side_effect=_side_effect),
            pytest.raises(KitDependencyError) as exc_info,
        ):
            load_kit(manifest)

        assert "missing-pkg>=2.0" in exc_info.value.missing_packages
        assert len(exc_info.value.missing_packages) == 1

    def test_no_deps_declared_passes(self) -> None:
        """Kits with no dependencies load without error (backward compat)."""
        manifest = _make_manifest(dependencies=[])

        result = load_kit(manifest)

        assert result == {}

    def test_dep_with_extras_parsed_correctly(self) -> None:
        """Dependency specifiers with extras are parsed to bare package name."""
        manifest = _make_manifest(dependencies=["httpx[http2]>=0.27"])

        with patch("beddel.tools.kits.distribution") as mock_dist:
            mock_dist.return_value = MagicMock()
            result = load_kit(manifest)

        assert result == {}
        # distribution() should be called with bare package name
        mock_dist.assert_called_once_with("httpx")


# ---------------------------------------------------------------------------
# SolutionKit model — dependencies and targets fields (subtask 5.3)
# ---------------------------------------------------------------------------


class TestSolutionKitDepsAndTargets:
    """Tests for SolutionKit with dependencies and targets fields."""

    def test_kit_with_deps_and_targets(self) -> None:
        """Valid kit.yaml with both dependencies and targets."""
        kit = SolutionKit(
            name="test-kit",
            version="0.1.0",
            description="Test",
            dependencies=["httpx>=0.27"],
            targets={"python": {"module": "test_kit"}},
        )

        assert kit.dependencies == ["httpx>=0.27"]
        assert kit.targets["python"]["module"] == "test_kit"

    def test_kit_backward_compat_no_deps_no_targets(self) -> None:
        """Kit without dependencies or targets defaults to empty (AC #7)."""
        kit = SolutionKit(
            name="test-kit",
            version="0.1.0",
            description="Test",
        )

        assert kit.dependencies == []
        assert kit.targets == {}

    def test_deps_are_just_strings(self) -> None:
        """Dependencies are plain strings — any format parses."""
        kit = SolutionKit(
            name="test-kit",
            version="0.1.0",
            description="Test",
            dependencies=["some-pkg", "another>=1.0", "weird[extra]~=2.0"],
        )

        assert len(kit.dependencies) == 3
        assert kit.dependencies[0] == "some-pkg"

    def test_multiple_targets(self) -> None:
        """Multiple language targets coexist."""
        kit = SolutionKit(
            name="test-kit",
            version="0.1.0",
            description="Test",
            targets={
                "python": {"module": "my_kit"},
                "typescript": {"package": "@my/kit"},
            },
        )

        assert "python" in kit.targets
        assert "typescript" in kit.targets


# ---------------------------------------------------------------------------
# KitAdapterDeclaration reconciliation (subtask 5.4)
# ---------------------------------------------------------------------------


class TestKitAdapterDeclarationReconciliation:
    """Tests that KitAdapterDeclaration validates identity formats."""

    def test_implementation_only(self) -> None:
        """Implementation shorthand is valid."""
        adapter = KitAdapterDeclaration(
            port="IAgentAdapter",
            implementation="OpenClawAgentAdapter",
        )

        assert adapter.implementation == "OpenClawAgentAdapter"
        assert adapter.name is None
        assert adapter.target is None

    def test_name_and_target(self) -> None:
        """Explicit name + target format is valid."""
        adapter = KitAdapterDeclaration(
            name="my-adapter",
            target="mod:Class",
            port="IPort",
        )

        assert adapter.name == "my-adapter"
        assert adapter.target == "mod:Class"

    def test_neither_provided_raises_validation_error(self) -> None:
        """Missing both implementation and (name+target) raises ValidationError."""
        with pytest.raises(ValidationError, match="implementation"):
            KitAdapterDeclaration(port="IPort")

    def test_name_without_target_raises_validation_error(self) -> None:
        """Name alone (without target or implementation) raises ValidationError."""
        with pytest.raises(ValidationError, match="implementation"):
            KitAdapterDeclaration(name="orphan", port="IPort")

    def test_all_three_provided_is_valid(self) -> None:
        """Providing both formats simultaneously is accepted."""
        adapter = KitAdapterDeclaration(
            name="my-adapter",
            target="mod:Class",
            port="IPort",
            implementation="MyImpl",
        )

        assert adapter.name == "my-adapter"
        assert adapter.implementation == "MyImpl"
