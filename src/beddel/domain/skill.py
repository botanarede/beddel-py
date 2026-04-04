"""Skill resolution domain service.

Provides :class:`SkillResolver` for resolving skill references against kit
manifests, and :func:`check_version_constraint` for semver constraint
evaluation.

Domain isolation: this module imports only from ``beddel.domain.models``,
``beddel.domain.kit``, ``beddel.domain.errors``, and ``beddel.error_codes``
— no adapters or integrations.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from beddel.domain.errors import SkillError
from beddel.domain.kit import KitManifest
from beddel.domain.models import SkillReference
from beddel.error_codes import (
    SKILL_BLOCKED,
    SKILL_KIT_NOT_FOUND,
    SKILL_NOT_ALLOWED,
    SKILL_VERSION_MISMATCH,
    SKILL_WORKFLOW_NOT_FOUND,
)

__all__ = ["SkillResolver", "check_version_constraint"]

_SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
_CONSTRAINT_RE = re.compile(r"^(>=|<=|!=|==|>|<|\^|~)?\s*(\d+\.\d+\.\d+)$")


def _parse_semver(version: str) -> tuple[int, int, int]:
    """Parse a ``MAJOR.MINOR.PATCH`` string into an integer tuple."""
    m = _SEMVER_RE.match(version.strip())
    if not m:
        msg = f"Invalid semver string: {version!r}"
        raise ValueError(msg)
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def check_version_constraint(version: str, constraint: str) -> bool:
    """Check whether *version* satisfies *constraint*.

    Supported operators: ``>=``, ``>``, ``<=``, ``<``, ``==``, ``!=``,
    ``^`` (caret — compatible release), ``~`` (tilde — patch-level
    compatible), and exact match (no operator).

    An empty *constraint* always returns ``True``.

    Caret semantics:
        - ``^1.x.y`` → ``>=1.x.y, <2.0.0`` (pin major for >=1)
        - ``^0.x.y`` → ``>=0.x.y, <0.(x+1).0`` (pin minor for 0.x)

    Tilde semantics:
        - ``~x.y.z`` → ``>=x.y.z, <x.(y+1).0`` (pin major.minor)

    Args:
        version: The actual version string (``MAJOR.MINOR.PATCH``).
        constraint: The constraint expression to evaluate against.

    Returns:
        ``True`` if the version satisfies the constraint.

    Raises:
        ValueError: If *version* or the version in *constraint* is not
            valid semver.
    """
    if not constraint or not constraint.strip():
        return True

    constraint = constraint.strip()
    m = _CONSTRAINT_RE.match(constraint)
    if not m:
        msg = f"Invalid version constraint: {constraint!r}"
        raise ValueError(msg)

    operator = m.group(1) or ""
    constraint_ver = _parse_semver(m.group(2))
    ver = _parse_semver(version)

    if operator == ">=":
        return ver >= constraint_ver
    if operator == ">":
        return ver > constraint_ver
    if operator == "<=":
        return ver <= constraint_ver
    if operator == "<":
        return ver < constraint_ver
    if operator == "==":
        return ver == constraint_ver
    if operator == "!=":
        return ver != constraint_ver
    if operator == "^":
        return _check_caret(ver, constraint_ver)
    if operator == "~":
        return _check_tilde(ver, constraint_ver)
    # Exact match (no operator)
    return ver == constraint_ver


def _check_caret(
    ver: tuple[int, int, int],
    constraint: tuple[int, int, int],
) -> bool:
    """Caret (``^``) compatible release check.

    For major >= 1: ``>=constraint, <(major+1).0.0``.
    For major == 0: ``>=constraint, <0.(minor+1).0``.
    """
    if ver < constraint:
        return False
    major, minor, _patch = constraint
    if major >= 1:
        return ver < (major + 1, 0, 0)
    # 0.x range — pin minor
    return ver < (0, minor + 1, 0)


def _check_tilde(
    ver: tuple[int, int, int],
    constraint: tuple[int, int, int],
) -> bool:
    """Tilde (``~``) patch-level compatible check.

    ``>=constraint, <major.(minor+1).0``.
    """
    if ver < constraint:
        return False
    major, minor, _patch = constraint
    return ver < (major, minor + 1, 0)


class SkillResolver:
    """Domain service for resolving skill references against kit manifests.

    Stateless — instantiate once and reuse, or create per call.
    """

    def resolve(
        self,
        ref: SkillReference,
        manifests: list[KitManifest],
        governance: dict[str, Any] | None = None,
    ) -> Path:
        """Resolve a skill reference to a workflow YAML path.

        Resolution order:
        1. Governance enforcement (fail fast on policy violations).
        2. Find kit by ``ref.kit`` name in *manifests*.
        3. Find workflow by ``ref.workflow`` name in the kit's workflows.
        4. Validate version constraint.
        5. Return ``manifest.root_path / workflow.path``.

        Args:
            ref: The skill reference to resolve.
            manifests: Available kit manifests to search.
            governance: Optional governance dict with ``policy``,
                ``allowed``, and ``blocked`` keys.

        Returns:
            Absolute path to the resolved workflow YAML file.

        Raises:
            SkillError: On governance violation, missing kit/workflow,
                or version mismatch.
        """
        # 1. Governance enforcement (before any resolution)
        self._enforce_governance(ref, governance)

        # 2. Find kit
        manifest = self._find_kit(ref, manifests)

        # 3. Find workflow
        workflow = self._find_workflow(ref, manifest)

        # 4. Version constraint
        if ref.version and not check_version_constraint(manifest.kit.version, ref.version):
            raise SkillError(
                code=SKILL_VERSION_MISMATCH,
                message=(
                    f"Kit {ref.kit!r} version {manifest.kit.version!r} "
                    f"does not satisfy constraint {ref.version!r}"
                ),
                details={
                    "kit": ref.kit,
                    "kit_version": manifest.kit.version,
                    "constraint": ref.version,
                },
            )

        # 5. Return resolved path
        return manifest.root_path / workflow.path

    @staticmethod
    def _find_kit(
        ref: SkillReference,
        manifests: list[KitManifest],
    ) -> KitManifest:
        """Locate the kit manifest matching ``ref.kit``."""
        for manifest in manifests:
            if manifest.kit.name == ref.kit:
                return manifest
        raise SkillError(
            code=SKILL_KIT_NOT_FOUND,
            message=f"Kit {ref.kit!r} not found in available manifests",
            details={"kit": ref.kit},
        )

    @staticmethod
    def _find_workflow(ref: SkillReference, manifest: KitManifest) -> Any:
        """Locate the workflow declaration matching ``ref.workflow``."""
        for wf in manifest.kit.workflows:
            if wf.name == ref.workflow:
                return wf
        raise SkillError(
            code=SKILL_WORKFLOW_NOT_FOUND,
            message=(f"Workflow {ref.workflow!r} not found in kit {ref.kit!r}"),
            details={"kit": ref.kit, "workflow": ref.workflow},
        )

    @staticmethod
    def _enforce_governance(
        ref: SkillReference,
        governance: dict[str, Any] | None,
    ) -> None:
        """Enforce governance policy before resolution."""
        if governance is None:
            return

        policy = governance.get("policy", "")

        if policy == "strict":
            allowed: list[str] = governance.get("allowed", [])
            if ref.kit not in allowed:
                raise SkillError(
                    code=SKILL_NOT_ALLOWED,
                    message=(f"Kit {ref.kit!r} is not in the allowed list (strict governance)"),
                    details={
                        "kit": ref.kit,
                        "policy": "strict",
                        "allowed": allowed,
                    },
                )

        elif policy == "permissive":
            blocked: list[str] = governance.get("blocked", [])
            if ref.kit in blocked:
                raise SkillError(
                    code=SKILL_BLOCKED,
                    message=(f"Kit {ref.kit!r} is blocked by governance policy"),
                    details={
                        "kit": ref.kit,
                        "policy": "permissive",
                        "blocked": blocked,
                    },
                )
