"""Kit discovery and loading for the Beddel SDK.

Provides :func:`discover_kits` — scans configured directories for
``kit.yaml`` manifests — :func:`load_kit` — resolves tool declarations
from a manifest into callable functions via ``importlib`` — and
:func:`load_kit_adapters` — resolves adapter declarations into
instantiated adapter objects.
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
from beddel.kits import BUNDLED_KITS_PATH

__all__ = ["discover_kits", "load_kit", "load_kit_adapters"]

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
            env var (colon-separated) or the 3-path defaults:
            bundled (``beddel/kits/``) → local (``./kits/``) → global
            (``~/.beddel/kits/``).

    Returns:
        A :class:`KitDiscoveryResult` with alphabetically sorted manifests
        and any detected tool name collisions.
    """
    # Determine source label for each path
    use_custom = False
    if paths is None:
        env_val = os.environ.get("BEDDEL_KIT_PATHS")
        if env_val:
            paths = [Path(p) for p in env_val.split(":") if p]
            use_custom = True
        else:
            paths = [BUNDLED_KITS_PATH, Path("./kits"), Path.home() / ".beddel" / "kits"]

    # Map each path to its source label (order matters for priority)
    _SOURCE_LABELS = {0: "bundled", 1: "local", 2: "global"}

    def _source_for(path_index: int) -> str:
        if use_custom:
            return "custom"
        return _SOURCE_LABELS.get(path_index, "local")

    manifests: list[KitManifest] = []
    for path_index, base in enumerate(paths):
        if not base.is_dir():
            continue
        source = _source_for(path_index)
        for child in sorted(base.iterdir()):
            if not child.is_dir():
                continue
            kit_yaml = child / "kit.yaml"
            if not kit_yaml.is_file():
                continue
            try:
                manifest = parse_kit_manifest(kit_yaml, source=source)
            except KitManifestError as exc:
                logger.warning("Skipping kit at %s: %s", kit_yaml, exc.message)
                continue
            manifests.append(manifest)

    # Deduplicate: later paths override earlier ones for same kit name.
    # Walk in order so the last occurrence (highest priority) wins.
    seen: dict[str, int] = {}
    for idx, m in enumerate(manifests):
        seen[m.kit.name] = idx
    manifests = [manifests[i] for i in sorted(seen.values())]

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


def load_kit_adapters(manifest: KitManifest) -> dict[tuple[str, str], Any]:
    """Resolve adapter declarations from a kit manifest into instances.

    Reads ``targets.python.adapters[]`` from the manifest, validates each
    entry has a ``name`` and ``target`` in ``module:class`` format, checks
    dependencies, and instantiates adapter classes via ``importlib``.

    Args:
        manifest: A validated :class:`KitManifest`.

    Returns:
        Dict mapping ``(port, name)`` tuples to adapter instances.
        For example: ``{("IAgentAdapter", "kiro-cli"): <instance>}``.

    Raises:
        KitDependencyError: If declared pip dependencies are not installed.
        KitManifestError: If an adapter is missing ``name`` or ``target``,
            or if the target cannot be imported.
    """
    from beddel.domain.kit import KitLanguageTarget

    targets_raw = manifest.kit.targets
    if not targets_raw or "python" not in targets_raw:
        return {}

    lang_target = KitLanguageTarget(**targets_raw["python"])

    if not lang_target.adapters:
        return {}

    # Dependency validation (same as load_kit)
    deps = lang_target.dependencies
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

    adapters: dict[tuple[str, str], Any] = {}
    for adapter_decl in lang_target.adapters:
        if not adapter_decl.name:
            raise KitManifestError(
                code=KIT_LOAD_FAILED,
                message=(
                    f"Adapter in kit '{manifest.kit.name}' is missing "
                    f"required 'name' field in targets.python.adapters"
                ),
                details={"kit": manifest.kit.name, "port": adapter_decl.port},
            )
        if not adapter_decl.target:
            raise KitManifestError(
                code=KIT_LOAD_FAILED,
                message=(
                    f"Adapter '{adapter_decl.name}' in kit "
                    f"'{manifest.kit.name}' is missing required 'target' "
                    f"field (expected 'module:class' format)"
                ),
                details={
                    "kit": manifest.kit.name,
                    "adapter": adapter_decl.name,
                },
            )
        if ":" not in adapter_decl.target:
            raise KitManifestError(
                code=KIT_LOAD_FAILED,
                message=(
                    f"Invalid adapter target format for "
                    f"'{adapter_decl.name}' in kit "
                    f"'{manifest.kit.name}': expected 'module:class', "
                    f"got '{adapter_decl.target}'"
                ),
                details={
                    "kit": manifest.kit.name,
                    "adapter": adapter_decl.name,
                    "target": adapter_decl.target,
                },
            )

        module_path, class_name = adapter_decl.target.rsplit(":", 1)
        try:
            mod = importlib.import_module(module_path)
        except ImportError as exc:
            raise KitManifestError(
                code=KIT_LOAD_FAILED,
                message=(
                    f"Cannot import module '{module_path}' for adapter "
                    f"'{adapter_decl.name}' in kit "
                    f"'{manifest.kit.name}': {exc}"
                ),
                details={
                    "kit": manifest.kit.name,
                    "adapter": adapter_decl.name,
                    "target": adapter_decl.target,
                },
            ) from exc
        try:
            cls = getattr(mod, class_name)
        except AttributeError as exc:
            raise KitManifestError(
                code=KIT_LOAD_FAILED,
                message=(
                    f"Module '{module_path}' has no attribute "
                    f"'{class_name}' for adapter '{adapter_decl.name}' "
                    f"in kit '{manifest.kit.name}'"
                ),
                details={
                    "kit": manifest.kit.name,
                    "adapter": adapter_decl.name,
                    "target": adapter_decl.target,
                },
            ) from exc

        adapters[(adapter_decl.port, adapter_decl.name)] = cls()

    return adapters
