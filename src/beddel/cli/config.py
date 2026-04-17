"""Beddel CLI configuration — kit and flow path resolution.

Implements a 3-layer configuration hierarchy:

1. **Project-local** (``.beddel.json`` in CWD or parent directories)
2. **Global** (``~/.config/beddel/config.json``)
3. **Interactive prompt** (when no kits found, asks user and saves to global)

Both files share the same JSON schema::

    {
        "kits_paths": ["/absolute/path/to/kits"],
        "flows_paths": ["/absolute/path/to/flows"]
    }

Paths in ``.beddel.json`` may be relative (resolved against the file's
parent directory).  Paths in the global config must be absolute.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import click

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GLOBAL_CONFIG_PATH: Path = Path("~/.config/beddel/config.json").expanduser()
"""XDG-compliant global config — same directory as credentials.json."""

PROJECT_CONFIG_NAME: str = ".beddel.json"
"""Project-local config filename."""


# ---------------------------------------------------------------------------
# Schema helpers
# ---------------------------------------------------------------------------


def _empty_config() -> dict[str, Any]:
    """Return a config dict with empty defaults."""
    return {"kits_paths": [], "flows_paths": []}


def _normalize_paths(paths: list[str], base_dir: Path) -> list[Path]:
    """Resolve a list of path strings to absolute ``Path`` objects.

    Relative paths are resolved against *base_dir*.
    """
    result: list[Path] = []
    for p in paths:
        resolved = Path(p)
        if not resolved.is_absolute():
            resolved = (base_dir / resolved).resolve()
        result.append(resolved)
    return result


# ---------------------------------------------------------------------------
# Project-local config (.beddel.json)
# ---------------------------------------------------------------------------


def find_project_config(start: Path | None = None) -> Path | None:
    """Walk up from *start* (default: CWD) looking for ``.beddel.json``.

    Returns the path to the file, or ``None`` if not found.
    """
    current = (start or Path.cwd()).resolve()
    for directory in [current, *current.parents]:
        candidate = directory / PROJECT_CONFIG_NAME
        if candidate.is_file():
            return candidate
    return None


def load_project_config(config_path: Path) -> dict[str, Any]:
    """Load and validate a project-local config file.

    Relative paths are resolved against the config file's parent directory.
    """
    raw = json.loads(config_path.read_text())
    base_dir = config_path.parent
    result = _empty_config()
    if "kits_paths" in raw:
        result["kits_paths"] = [str(p) for p in _normalize_paths(raw["kits_paths"], base_dir)]
    if "flows_paths" in raw:
        result["flows_paths"] = [str(p) for p in _normalize_paths(raw["flows_paths"], base_dir)]
    return result


# ---------------------------------------------------------------------------
# Global config (~/.config/beddel/config.json)
# ---------------------------------------------------------------------------


def load_global_config() -> dict[str, Any]:
    """Load the global config file, returning empty defaults if absent."""
    if not GLOBAL_CONFIG_PATH.exists():
        return _empty_config()
    try:
        raw = json.loads(GLOBAL_CONFIG_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return _empty_config()
    result = _empty_config()
    if "kits_paths" in raw:
        result["kits_paths"] = raw["kits_paths"]
    if "flows_paths" in raw:
        result["flows_paths"] = raw["flows_paths"]
    return result


def save_global_config(data: dict[str, Any]) -> None:
    """Persist config to the global config file with ``0o644`` permissions."""
    GLOBAL_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    GLOBAL_CONFIG_PATH.write_text(json.dumps(data, indent=2) + "\n")
    GLOBAL_CONFIG_PATH.chmod(0o644)


# ---------------------------------------------------------------------------
# Merged resolution
# ---------------------------------------------------------------------------


def resolve_kits_paths() -> list[Path]:
    """Return the merged list of kit directories to scan.

    Resolution order (first non-empty wins):
    1. ``.beddel.json`` in CWD or parent
    2. ``~/.config/beddel/config.json``
    3. Empty list (caller may prompt interactively)
    """
    # 1. Project-local
    project_cfg_path = find_project_config()
    if project_cfg_path is not None:
        cfg = load_project_config(project_cfg_path)
        if cfg["kits_paths"]:
            return [Path(p) for p in cfg["kits_paths"]]

    # 2. Global
    global_cfg = load_global_config()
    if global_cfg["kits_paths"]:
        return [Path(p) for p in global_cfg["kits_paths"]]

    # 3. Nothing configured
    return []


def resolve_flows_paths() -> list[Path]:
    """Return the merged list of flow directories.

    Same resolution order as :func:`resolve_kits_paths`.
    """
    project_cfg_path = find_project_config()
    if project_cfg_path is not None:
        cfg = load_project_config(project_cfg_path)
        if cfg["flows_paths"]:
            return [Path(p) for p in cfg["flows_paths"]]

    global_cfg = load_global_config()
    if global_cfg["flows_paths"]:
        return [Path(p) for p in global_cfg["flows_paths"]]

    return []


# ---------------------------------------------------------------------------
# Interactive prompt (used by _ensure_kit_paths when no kits found)
# ---------------------------------------------------------------------------


def prompt_kits_path() -> Path | None:
    """Ask the user for a kits directory and save to global config.

    Returns the chosen path, or ``None`` if the user declines.
    Only prompts when running in an interactive terminal.
    """
    if not sys.stdin.isatty():
        return None

    click.echo("No kits directory configured.", err=True)
    path_str = click.prompt(
        "Enter path to your kits directory (or 'skip' to continue without kits)",
        default="skip",
        show_default=False,
    )

    if path_str.strip().lower() == "skip":
        return None

    kits_path = Path(path_str).expanduser().resolve()
    if not kits_path.is_dir():
        click.echo(f"Directory not found: {kits_path}", err=True)
        return None

    # Save to global config
    cfg = load_global_config()
    cfg["kits_paths"] = [str(kits_path)]
    save_global_config(cfg)
    click.echo(f"Saved kits path to {GLOBAL_CONFIG_PATH}", err=True)
    return kits_path
