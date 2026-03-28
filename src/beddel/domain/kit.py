"""Solution Kit domain models for kit.yaml manifest declarations.

This module defines the Pydantic models that represent a Solution Kit manifest.
A kit bundles tools, workflows, adapters, and contracts into a distributable
unit with a validated, typed schema.

It also provides :func:`parse_kit_manifest` for loading and validating a
``kit.yaml`` file into a :class:`KitManifest` wrapper.

Domain isolation: this module imports only from ``pydantic``, ``pyyaml``,
and ``beddel.domain.errors`` — no adapters or integrations.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator

from beddel.domain.errors import KitManifestError
from beddel.error_codes import KIT_MANIFEST_INVALID, KIT_MANIFEST_NOT_FOUND

__all__ = [
    "KitAdapterDeclaration",
    "KitContractDeclaration",
    "KitManifest",
    "KitToolDeclaration",
    "KitWorkflowDeclaration",
    "SolutionKit",
    "parse_kit_manifest",
]

_KEBAB_CASE_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")


class KitToolDeclaration(BaseModel):
    """Declaration of a tool provided by a Solution Kit.

    Maps a logical tool name to a Python callable target using
    ``module:function`` format — the same pattern as the inline
    :class:`~beddel.domain.models.ToolDeclaration`.

    Attributes:
        name: Logical name used to reference this tool.
        target: Import path in ``module:function`` format.
        description: Optional human-readable description.
        category: Tool category for taxonomy grouping.
    """

    name: str
    target: str
    description: str | None = None
    category: str = "general"


class KitWorkflowDeclaration(BaseModel):
    """Declaration of a workflow YAML asset provided by a Solution Kit.

    Attributes:
        name: Logical name used to reference this workflow.
        path: Path to the workflow YAML file, relative to the kit root.
        description: Optional human-readable description.
    """

    name: str
    path: str
    description: str | None = None


class KitAdapterDeclaration(BaseModel):
    """Declaration of an adapter binding provided by a Solution Kit.

    Attributes:
        name: Logical name used to reference this adapter.
        target: Import path in ``module:class`` format.
        port: Port interface name that this adapter implements.
    """

    name: str
    target: str
    port: str


class KitContractDeclaration(BaseModel):
    """Declaration of a contract (schema) provided by a Solution Kit.

    Attributes:
        name: Logical name used to reference this contract.
        schema_path: Path to the schema file, relative to the kit root.
        description: Optional human-readable description.
    """

    name: str
    schema_path: str
    description: str | None = None


class SolutionKit(BaseModel):
    """Top-level model for a ``kit.yaml`` manifest.

    Represents a complete Solution Kit declaration with validated metadata
    and lists of tool, workflow, adapter, and contract declarations.

    Attributes:
        name: Unique kit identifier in kebab-case (e.g. ``my-kit``).
        version: Semantic version string (e.g. ``0.1.0``).
        description: Human-readable kit description.
        author: Optional author attribution.
        tools: Tool declarations bundled in this kit.
        workflows: Workflow YAML asset declarations.
        adapters: Adapter binding declarations.
        contracts: Contract/schema declarations.
    """

    name: str
    version: str
    description: str
    author: str | None = None
    tools: list[KitToolDeclaration] = Field(default_factory=list)
    workflows: list[KitWorkflowDeclaration] = Field(default_factory=list)
    adapters: list[KitAdapterDeclaration] = Field(default_factory=list)
    contracts: list[KitContractDeclaration] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def _validate_name(cls, v: str) -> str:
        if not _KEBAB_CASE_RE.match(v):
            msg = (
                f"Kit name must be kebab-case (lowercase alphanumeric "
                f"segments separated by hyphens), got: {v!r}"
            )
            raise ValueError(msg)
        return v

    @field_validator("version")
    @classmethod
    def _validate_version(cls, v: str) -> str:
        if not _SEMVER_RE.match(v):
            msg = f"Kit version must be semver format (MAJOR.MINOR.PATCH), got: {v!r}"
            raise ValueError(msg)
        return v


@dataclass(frozen=True)
class KitManifest:
    """Immutable wrapper around a validated :class:`SolutionKit`.

    Produced by :func:`parse_kit_manifest` after loading and validating a
    ``kit.yaml`` file.

    Attributes:
        kit: The validated ``SolutionKit`` Pydantic model.
        root_path: Absolute path to the kit directory (parent of ``kit.yaml``).
        loaded_at: Timezone-aware UTC timestamp of when the manifest was loaded.
    """

    kit: SolutionKit
    root_path: Path
    loaded_at: datetime


def parse_kit_manifest(path: Path) -> KitManifest:
    """Load and validate a ``kit.yaml`` file into a :class:`KitManifest`.

    Args:
        path: Path to the ``kit.yaml`` file.

    Returns:
        A frozen :class:`KitManifest` wrapping the validated model.

    Raises:
        KitManifestError: ``BEDDEL-KIT-651`` if the file is not found,
            ``BEDDEL-KIT-650`` on YAML syntax errors or Pydantic validation
            failures.
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise KitManifestError(
            code=KIT_MANIFEST_NOT_FOUND,
            message=f"Kit manifest not found: {path}",
            details={"path": str(path)},
        ) from None

    try:
        data: Any = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise KitManifestError(
            code=KIT_MANIFEST_INVALID,
            message=f"Invalid YAML in kit manifest: {exc}",
            details={"path": str(path)},
        ) from exc

    try:
        kit = SolutionKit.model_validate(data)
    except ValidationError as exc:
        raise KitManifestError(
            code=KIT_MANIFEST_INVALID,
            message=f"Kit manifest validation failed: {exc.error_count()} error(s)",
            details={
                "path": str(path),
                "errors": exc.errors(),
            },
        ) from exc

    return KitManifest(
        kit=kit,
        root_path=path.parent.resolve(),
        loaded_at=datetime.now(tz=UTC),
    )
