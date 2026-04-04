"""Unit tests for beddel.domain.skill — SkillResolver and check_version_constraint."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from beddel.domain.errors import SkillError
from beddel.domain.kit import KitManifest, KitWorkflowDeclaration, SolutionKit
from beddel.domain.models import SkillReference
from beddel.domain.skill import SkillResolver, check_version_constraint
from beddel.error_codes import (
    SKILL_BLOCKED,
    SKILL_KIT_NOT_FOUND,
    SKILL_NOT_ALLOWED,
    SKILL_VERSION_MISMATCH,
    SKILL_WORKFLOW_NOT_FOUND,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_manifest(
    name: str = "my-kit",
    version: str = "1.0.0",
    workflows: list[KitWorkflowDeclaration] | None = None,
    root: Path | None = None,
) -> KitManifest:
    """Build a minimal KitManifest for testing."""
    wfs = workflows or [
        KitWorkflowDeclaration(
            name="create-epic",
            path="workflows/create-epic.yaml",
        ),
    ]
    kit = SolutionKit(
        name=name,
        version=version,
        description=f"Test kit {name}",
        workflows=wfs,
    )
    return KitManifest(
        kit=kit,
        root_path=root or Path("/kits") / name,
        loaded_at=datetime.now(tz=UTC),
    )


# ===================================================================
# check_version_constraint tests
# ===================================================================


class TestCheckVersionConstraint:
    """Tests for check_version_constraint — all operators."""

    # -- Empty / no constraint ------------------------------------------

    def test_empty_constraint_always_true(self) -> None:
        assert check_version_constraint("1.2.3", "") is True

    def test_whitespace_constraint_always_true(self) -> None:
        assert check_version_constraint("0.1.0", "   ") is True

    # -- Comparison operators -------------------------------------------

    @pytest.mark.parametrize(
        ("version", "constraint", "expected"),
        [
            ("1.0.0", ">=1.0.0", True),
            ("1.0.1", ">=1.0.0", True),
            ("0.9.9", ">=1.0.0", False),
            ("2.0.0", ">=1.0.0", True),
        ],
    )
    def test_gte(self, version: str, constraint: str, expected: bool) -> None:
        assert check_version_constraint(version, constraint) is expected

    @pytest.mark.parametrize(
        ("version", "constraint", "expected"),
        [
            ("1.0.1", ">1.0.0", True),
            ("1.0.0", ">1.0.0", False),
            ("0.9.9", ">1.0.0", False),
        ],
    )
    def test_gt(self, version: str, constraint: str, expected: bool) -> None:
        assert check_version_constraint(version, constraint) is expected

    @pytest.mark.parametrize(
        ("version", "constraint", "expected"),
        [
            ("1.0.0", "<=1.0.0", True),
            ("0.9.9", "<=1.0.0", True),
            ("1.0.1", "<=1.0.0", False),
        ],
    )
    def test_lte(self, version: str, constraint: str, expected: bool) -> None:
        assert check_version_constraint(version, constraint) is expected

    @pytest.mark.parametrize(
        ("version", "constraint", "expected"),
        [
            ("0.9.9", "<1.0.0", True),
            ("1.0.0", "<1.0.0", False),
            ("1.0.1", "<1.0.0", False),
        ],
    )
    def test_lt(self, version: str, constraint: str, expected: bool) -> None:
        assert check_version_constraint(version, constraint) is expected

    @pytest.mark.parametrize(
        ("version", "constraint", "expected"),
        [
            ("1.0.0", "==1.0.0", True),
            ("1.0.1", "==1.0.0", False),
        ],
    )
    def test_eq(self, version: str, constraint: str, expected: bool) -> None:
        assert check_version_constraint(version, constraint) is expected

    @pytest.mark.parametrize(
        ("version", "constraint", "expected"),
        [
            ("1.0.1", "!=1.0.0", True),
            ("1.0.0", "!=1.0.0", False),
        ],
    )
    def test_neq(self, version: str, constraint: str, expected: bool) -> None:
        assert check_version_constraint(version, constraint) is expected

    # -- Caret operator -------------------------------------------------

    @pytest.mark.parametrize(
        ("version", "constraint", "expected"),
        [
            # ^1.2.3 → >=1.2.3, <2.0.0
            ("1.2.3", "^1.2.3", True),
            ("1.9.9", "^1.2.3", True),
            ("2.0.0", "^1.2.3", False),
            ("1.2.2", "^1.2.3", False),
            # ^0.2.0 → >=0.2.0, <0.3.0 (pin minor for 0.x)
            ("0.2.0", "^0.2.0", True),
            ("0.2.9", "^0.2.0", True),
            ("0.3.0", "^0.2.0", False),
            ("0.1.9", "^0.2.0", False),
        ],
    )
    def test_caret(self, version: str, constraint: str, expected: bool) -> None:
        assert check_version_constraint(version, constraint) is expected

    # -- Tilde operator -------------------------------------------------

    @pytest.mark.parametrize(
        ("version", "constraint", "expected"),
        [
            # ~0.1.0 → >=0.1.0, <0.2.0
            ("0.1.0", "~0.1.0", True),
            ("0.1.9", "~0.1.0", True),
            ("0.2.0", "~0.1.0", False),
            ("0.0.9", "~0.1.0", False),
            # ~1.2.3 → >=1.2.3, <1.3.0
            ("1.2.3", "~1.2.3", True),
            ("1.2.9", "~1.2.3", True),
            ("1.3.0", "~1.2.3", False),
        ],
    )
    def test_tilde(self, version: str, constraint: str, expected: bool) -> None:
        assert check_version_constraint(version, constraint) is expected

    # -- Exact match (no operator) --------------------------------------

    def test_exact_match(self) -> None:
        assert check_version_constraint("1.0.0", "1.0.0") is True

    def test_exact_mismatch(self) -> None:
        assert check_version_constraint("1.0.1", "1.0.0") is False

    # -- Invalid inputs -------------------------------------------------

    def test_invalid_version_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid semver"):
            check_version_constraint("not-a-version", ">=1.0.0")

    def test_invalid_constraint_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid version constraint"):
            check_version_constraint("1.0.0", ">>1.0.0")


# ===================================================================
# SkillResolver.resolve tests
# ===================================================================


class TestSkillResolverResolve:
    """Tests for SkillResolver.resolve — happy path and error cases."""

    def setup_method(self) -> None:
        self.resolver = SkillResolver()
        self.manifest = _make_manifest(
            name="software-development-kit",
            version="0.2.0",
            workflows=[
                KitWorkflowDeclaration(
                    name="create-epic",
                    path="workflows/create-epic.yaml",
                ),
                KitWorkflowDeclaration(
                    name="review-code",
                    path="workflows/review-code.yaml",
                ),
            ],
        )

    # -- Happy path -----------------------------------------------------

    def test_resolve_happy_path(self) -> None:
        ref = SkillReference(
            kit="software-development-kit",
            workflow="create-epic",
            version=">=0.1.0",
        )
        result = self.resolver.resolve(ref, [self.manifest])
        expected = Path("/kits/software-development-kit/workflows/create-epic.yaml")
        assert result == expected

    def test_resolve_no_version_constraint(self) -> None:
        ref = SkillReference(
            kit="software-development-kit",
            workflow="create-epic",
        )
        result = self.resolver.resolve(ref, [self.manifest])
        expected = Path("/kits/software-development-kit/workflows/create-epic.yaml")
        assert result == expected

    def test_resolve_second_workflow(self) -> None:
        ref = SkillReference(
            kit="software-development-kit",
            workflow="review-code",
            version="^0.2.0",
        )
        result = self.resolver.resolve(ref, [self.manifest])
        expected = Path("/kits/software-development-kit/workflows/review-code.yaml")
        assert result == expected

    # -- Kit not found --------------------------------------------------

    def test_kit_not_found(self) -> None:
        ref = SkillReference(kit="nonexistent-kit", workflow="create-epic")
        with pytest.raises(SkillError) as exc_info:
            self.resolver.resolve(ref, [self.manifest])
        assert exc_info.value.code == SKILL_KIT_NOT_FOUND

    # -- Workflow not found ---------------------------------------------

    def test_workflow_not_found(self) -> None:
        ref = SkillReference(
            kit="software-development-kit",
            workflow="nonexistent-workflow",
        )
        with pytest.raises(SkillError) as exc_info:
            self.resolver.resolve(ref, [self.manifest])
        assert exc_info.value.code == SKILL_WORKFLOW_NOT_FOUND

    # -- Version mismatch -----------------------------------------------

    def test_version_mismatch(self) -> None:
        ref = SkillReference(
            kit="software-development-kit",
            workflow="create-epic",
            version=">=1.0.0",
        )
        with pytest.raises(SkillError) as exc_info:
            self.resolver.resolve(ref, [self.manifest])
        assert exc_info.value.code == SKILL_VERSION_MISMATCH
        assert "0.2.0" in exc_info.value.message

    # -- Multiple manifests ---------------------------------------------

    def test_resolve_picks_correct_kit_from_multiple(self) -> None:
        other = _make_manifest(name="other-kit", version="3.0.0")
        ref = SkillReference(
            kit="software-development-kit",
            workflow="create-epic",
            version=">=0.1.0",
        )
        result = self.resolver.resolve(ref, [other, self.manifest])
        assert result == Path("/kits/software-development-kit/workflows/create-epic.yaml")


# ===================================================================
# Governance enforcement tests
# ===================================================================


class TestSkillResolverGovernance:
    """Tests for governance enforcement in SkillResolver.resolve."""

    def setup_method(self) -> None:
        self.resolver = SkillResolver()
        self.manifest = _make_manifest(
            name="software-development-kit",
            version="1.0.0",
        )
        self.ref = SkillReference(
            kit="software-development-kit",
            workflow="create-epic",
        )

    # -- Strict policy --------------------------------------------------

    def test_strict_allowed(self) -> None:
        governance = {
            "policy": "strict",
            "allowed": ["software-development-kit"],
        }
        result = self.resolver.resolve(self.ref, [self.manifest], governance)
        assert result == Path("/kits/software-development-kit/workflows/create-epic.yaml")

    def test_strict_denied(self) -> None:
        governance = {
            "policy": "strict",
            "allowed": ["other-kit"],
        }
        with pytest.raises(SkillError) as exc_info:
            self.resolver.resolve(self.ref, [self.manifest], governance)
        assert exc_info.value.code == SKILL_NOT_ALLOWED
        assert "strict" in exc_info.value.message

    # -- Permissive policy ----------------------------------------------

    def test_permissive_allowed(self) -> None:
        governance = {
            "policy": "permissive",
            "blocked": ["malicious-kit"],
        }
        result = self.resolver.resolve(self.ref, [self.manifest], governance)
        assert result == Path("/kits/software-development-kit/workflows/create-epic.yaml")

    def test_permissive_blocked(self) -> None:
        governance = {
            "policy": "permissive",
            "blocked": ["software-development-kit"],
        }
        with pytest.raises(SkillError) as exc_info:
            self.resolver.resolve(self.ref, [self.manifest], governance)
        assert exc_info.value.code == SKILL_BLOCKED

    # -- No governance --------------------------------------------------

    def test_no_governance_allows_all(self) -> None:
        result = self.resolver.resolve(self.ref, [self.manifest], None)
        assert result == Path("/kits/software-development-kit/workflows/create-epic.yaml")

    def test_no_governance_default(self) -> None:
        """resolve() without governance parameter defaults to allow-all."""
        result = self.resolver.resolve(self.ref, [self.manifest])
        assert result == Path("/kits/software-development-kit/workflows/create-epic.yaml")

    # -- Governance before resolution -----------------------------------

    def test_governance_fails_before_kit_lookup(self) -> None:
        """Strict governance rejects even if kit doesn't exist."""
        ref = SkillReference(kit="nonexistent-kit", workflow="anything")
        governance = {"policy": "strict", "allowed": ["other-kit"]}
        with pytest.raises(SkillError) as exc_info:
            self.resolver.resolve(ref, [self.manifest], governance)
        # Should be SKILL_NOT_ALLOWED, not SKILL_KIT_NOT_FOUND
        assert exc_info.value.code == SKILL_NOT_ALLOWED
