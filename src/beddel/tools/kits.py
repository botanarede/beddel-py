"""Kit discovery and loading for the Beddel SDK.

Provides :func:`discover_kits` — scans configured directories for
``kit.yaml`` manifests — and :func:`load_kit` — resolves tool declarations
from a manifest into callable functions via ``importlib``.
"""

from __future__ import annotations

import importlib
import logging
import os
import re
from collections import defaultdict
from collections.abc import Callable
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path
from typing import Any

from beddel.domain.errors import KitDependencyError, KitManifestError
from beddel.domain.kit import KitCollision, KitDiscoveryResult, KitManifest, parse_kit_manifest
from beddel.error_codes import KIT_DEPENDENCY_MISSING, KIT_LOAD_FAILED

__all__ = ["discover_kits", "load_kit"]

logger = logging.getLogger(__name__)


def _parse_package_name(specifier: str) -> str:
    """Extract package name from a PEP 508 dependency specifier.

    Strips version constraints (``>=``, ``<``, ``~=``, etc.), extras
    (``[…]``), and environment markers (``;``).
    """
    return re.split(r"[><=!~\[;]", specifier)[0].strip()


def _validate_dependencies(deps: list[str]) -> list[str]:
    """Return dependency specifiers whose packages are not installed."""
    missing: list[str] = []
    for dep in deps:
        pkg = _parse_package_name(dep)
        try:
            distribution(pkg)
        except PackageNotFoundError:
            missing.append(dep)
    return missing


def discover_kits(paths: list[Path] | None = None) -> KitDiscoveryResult:
    """Scan directories for ``kit.yaml`` files and return validated manifests.

    Args:
        paths: Directories to scan. If *None*, uses ``BEDDEL_KIT_PATHS``
            env var (colon-separated) or the defaults ``./kits/`` and
            ``~/.beddel/kits/``.

    Returns:
        A :class:`KitDiscoveryResult` with alphabetically sorted manifests
        and any detected tool name collisions.
    """
    if paths is None:
        env_val = os.environ.get("BEDDEL_KIT_PATHS")
        if env_val:
            paths = [Path(p) for p in env_val.split(":") if p]
        else:
            paths = [Path("./kits"), Path.home() / ".beddel" / "kits"]

    manifests: list[KitManifest] = []
    for base in paths:
        if not base.is_dir():
            continue
        for child in sorted(base.iterdir()):
            if not child.is_dir():
                continue
            kit_yaml = child / "kit.yaml"
            if not kit_yaml.is_file():
                continue
            try:
                manifest = parse_kit_manifest(kit_yaml)
            except KitManifestError as exc:
                logger.warning("Skipping kit at %s: %s", kit_yaml, exc.message)
                continue
            manifests.append(manifest)

    manifests.sort(key=lambda m: m.kit.name)

    # Detect collisions: tool names declared by 2+ kits
    tool_to_kits: dict[str, list[str]] = defaultdict(list)
    for m in manifests:
        for tool_decl in m.kit.tools:
            tool_to_kits[tool_decl.name].append(m.kit.name)

    collisions = [
        KitCollision(tool_name=name, kit_names=kits)
        for name, kits in sorted(tool_to_kits.items())
        if len(kits) > 1
    ]

    return KitDiscoveryResult(manifests=manifests, collisions=collisions)


def load_kit(manifest: KitManifest) -> dict[str, Callable[..., Any]]:
    """Resolve tool declarations from a kit manifest into callables.

    Args:
        manifest: A validated :class:`KitManifest`.

    Returns:
        Dict mapping tool names to their callable implementations.

    Raises:
        KitDependencyError: ``BEDDEL-KIT-653`` if declared pip dependencies
            are not installed.
        KitManifestError: ``BEDDEL-KIT-652`` if a tool target cannot be
            imported or the function attribute is missing.
    """
    # --- Dependency validation -------------------------------------------
    deps = manifest.kit.dependencies
    if deps:
        missing = _validate_dependencies(deps)
        if missing:
            pkg_list = ", ".join(missing)
            raise KitDependencyError(
                code=KIT_DEPENDENCY_MISSING,
                message=(
                    f"Kit '{manifest.kit.name}' requires packages that are "
                    f"not installed: {pkg_list}. "
                    f"Install them with: pip install {' '.join(missing)}"
                ),
                missing_packages=missing,
                details={"kit": manifest.kit.name, "missing": missing},
            )

    # --- Tool resolution -------------------------------------------------
    tools: dict[str, Callable[..., Any]] = {}
    for tool_decl in manifest.kit.tools:
        if ":" not in tool_decl.target:
            raise KitManifestError(
                code=KIT_LOAD_FAILED,
                message=(
                    f"Invalid tool target format for '{tool_decl.name}' "
                    f"in kit '{manifest.kit.name}': expected "
                    f"'module:function', got '{tool_decl.target}'"
                ),
                details={
                    "kit": manifest.kit.name,
                    "tool": tool_decl.name,
                    "target": tool_decl.target,
                },
            )
        module_path, func_name = tool_decl.target.rsplit(":", 1)
        try:
            mod = importlib.import_module(module_path)
        except ImportError as exc:
            raise KitManifestError(
                code=KIT_LOAD_FAILED,
                message=(
                    f"Cannot import module '{module_path}' for tool "
                    f"'{tool_decl.name}' in kit '{manifest.kit.name}': {exc}"
                ),
                details={
                    "kit": manifest.kit.name,
                    "tool": tool_decl.name,
                    "target": tool_decl.target,
                },
            ) from exc
        try:
            fn = getattr(mod, func_name)
        except AttributeError as exc:
            raise KitManifestError(
                code=KIT_LOAD_FAILED,
                message=(
                    f"Module '{module_path}' has no attribute "
                    f"'{func_name}' for tool '{tool_decl.name}' "
                    f"in kit '{manifest.kit.name}'"
                ),
                details={
                    "kit": manifest.kit.name,
                    "tool": tool_decl.name,
                    "target": tool_decl.target,
                },
            ) from exc
        tools[tool_decl.name] = fn
    return tools
