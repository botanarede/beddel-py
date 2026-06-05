"""Beddel CLI configuration — kit/flow path and mode resolution.

Implements a 3-layer configuration hierarchy:

1. **Project-local** (``.beddel.json`` in CWD or parent directories)
2. **Global** (``~/.config/beddel/config.json``)
3. **Interactive prompt** (when no kits found, asks user and saves to global)

Both files use JSONC format (JSON with Comments) — single-line ``//``
comments are stripped before parsing.  This follows the same convention
as VS Code (``settings.json``), TypeScript (``tsconfig.json``), and
ESLint configs::

    {
        "kits_paths": ["/absolute/path/to/kits"],
        "flows_paths": ["/absolute/path/to/flows"],
        "dev": true,
        // "dashboard_url": "https://connect.beddel.com.br",
        "dashboard_url": "http://localhost:3000",
        "llm_provider": "gemini"
    }

Paths in ``.beddel.json`` may be relative (resolved against the file's
parent directory).  Paths in the global config must be absolute.
"""

from __future__ import annotations

import json
import re
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
# JSONC support (JSON with Comments)
# ---------------------------------------------------------------------------

# Matches single-line // comments that are NOT inside a JSON string value.
# Strategy: split each line at the first // that is outside quotes.
_JSONC_LINE_COMMENT = re.compile(
    r'("(?:[^"\\]|\\.)*")|//.*$',
)


def _strip_jsonc_comments(text: str) -> str:
    """Remove single-line ``//`` comments from JSONC text.

    Preserves ``//`` inside quoted strings (e.g. URLs like
    ``"http://localhost:3000"``).  Does NOT handle block comments
    ``/* ... */`` — those are rare in config files.
    """

    def _replace(match: re.Match[str]) -> str:
        # Group 1 is a quoted string — keep it intact
        if match.group(1) is not None:
            return match.group(1)
        # Otherwise it's a // comment — remove it
        return ""

    lines = text.split("\n")
    stripped = [_JSONC_LINE_COMMENT.sub(_replace, line) for line in lines]
    return "\n".join(stripped)


# ---------------------------------------------------------------------------
# Schema helpers
# ---------------------------------------------------------------------------


_SENTINEL: object = object()
"""Internal sentinel to distinguish 'key absent' from ``None``."""

_DASHBOARD_URL_DEV: str = "http://localhost:3000"
"""Default dashboard URL for dev mode."""

_DASHBOARD_URL_REMOTE: str = "https://connect.beddel.com.br"
"""Default dashboard URL for remote mode."""


def _empty_config() -> dict[str, Any]:
    """Return a config dict with empty defaults."""
    return {
        "kits_paths": [],
        "flows_paths": [],
        "dev": _SENTINEL,
        "dashboard_url": _SENTINEL,
        "llm_provider": _SENTINEL,
        "agent_engine": _SENTINEL,
        "default_model": _SENTINEL,
        "project_name": _SENTINEL,
        "features": _SENTINEL,
    }


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
    raw = json.loads(_strip_jsonc_comments(config_path.read_text()))
    base_dir = config_path.parent
    result = _empty_config()
    if "kits_paths" in raw:
        result["kits_paths"] = [str(p) for p in _normalize_paths(raw["kits_paths"], base_dir)]
    if "flows_paths" in raw:
        result["flows_paths"] = [str(p) for p in _normalize_paths(raw["flows_paths"], base_dir)]
    if "dev" in raw:
        result["dev"] = bool(raw["dev"])
    if "dashboard_url" in raw:
        result["dashboard_url"] = str(raw["dashboard_url"])
    if "llm_provider" in raw:
        result["llm_provider"] = str(raw["llm_provider"])
    if "agent_engine" in raw:
        result["agent_engine"] = str(raw["agent_engine"])
    return result


# ---------------------------------------------------------------------------
# Global config (~/.config/beddel/config.json)
# ---------------------------------------------------------------------------


def load_global_config() -> dict[str, Any]:
    """Load the global config file, returning empty defaults if absent."""
    if not GLOBAL_CONFIG_PATH.exists():
        return _empty_config()
    try:
        raw = json.loads(_strip_jsonc_comments(GLOBAL_CONFIG_PATH.read_text()))
    except (json.JSONDecodeError, OSError):
        return _empty_config()
    result = _empty_config()
    if "kits_paths" in raw:
        result["kits_paths"] = raw["kits_paths"]
    if "flows_paths" in raw:
        result["flows_paths"] = raw["flows_paths"]
    if "dev" in raw:
        result["dev"] = bool(raw["dev"])
    if "dashboard_url" in raw:
        result["dashboard_url"] = str(raw["dashboard_url"])
    if "llm_provider" in raw:
        result["llm_provider"] = str(raw["llm_provider"])
    if "agent_engine" in raw:
        result["agent_engine"] = str(raw["agent_engine"])
    if "default_model" in raw:
        result["default_model"] = str(raw["default_model"])
    if "project_name" in raw:
        result["project_name"] = str(raw["project_name"])
    if "features" in raw:
        result["features"] = raw["features"]
    return result


def save_global_config(data: dict[str, Any]) -> None:
    """Persist config to the global config file with ``0o644`` permissions."""
    GLOBAL_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    GLOBAL_CONFIG_PATH.write_text(json.dumps(data, indent=2) + "\n")
    GLOBAL_CONFIG_PATH.chmod(0o644)


def save_wizard_config(
    config_json: str = "",
    name: str | None = None,
    provider: str | None = None,
    project_type: str | None = None,
) -> dict[str, Any]:
    """Persist onboarding-wizard config to the global config file.

    Parses the LLM-generated config (tolerating surrounding markdown fences
    or prose) and merges ``llm_provider``, ``default_model``,
    ``project_name``, and ``features`` into the existing global config.

    Args:
        config_json: The generated config as a JSON string.
        name: Optional user name (unused in persisted config; for context).
        provider: Fallback provider when ``config_json`` omits it.
        project_type: Optional project type (for context).

    Returns:
        A dict with ``saved`` (bool), ``path`` (str), and the persisted
        ``config`` dict.
    """
    parsed: dict[str, Any] = {}
    if config_json:
        text = str(config_json)
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            try:
                parsed = json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                parsed = {}

    cfg = {k: v for k, v in load_global_config().items() if v is not _SENTINEL}

    llm_provider = parsed.get("llm_provider") or provider
    if llm_provider:
        cfg["llm_provider"] = llm_provider
    if parsed.get("default_model"):
        cfg["default_model"] = parsed["default_model"]
    if parsed.get("project_name"):
        cfg["project_name"] = parsed["project_name"]
    if "features" in parsed:
        cfg["features"] = parsed["features"]

    save_global_config(cfg)
    return {"saved": True, "path": str(GLOBAL_CONFIG_PATH), "config": cfg}


def save_setup(
    llm_provider: str = "",
    default_model: str = "",
    project_name: str = "",
    dashboard_url: str = "",
    agent_engine: str = "",
) -> dict[str, Any]:
    """Persist setup form data to the appropriate stores.

    Personal preferences (llm_provider, default_model, project_name) go to
    SQLite ``user_prefs``.  Project infrastructure (dashboard_url,
    agent_engine) goes to ``config.json``.

    Also sets ``onboarding_done=true`` in SQLite to mark completion.

    Args:
        llm_provider: Preferred LLM provider (gemini, litellm, openai).
        default_model: Default model identifier for the provider.
        project_name: Project slug for identification.
        dashboard_url: Remote dashboard URL (infra setting).
        agent_engine: Google Cloud project for Agent Engine (infra setting).

    Returns:
        A dict with ``saved`` (bool) and summary of what was persisted.
    """
    import asyncio

    from beddel.adapters.index_store import IndexStore

    # ── SQLite: personal preferences ──
    store = IndexStore()
    prefs: dict[str, str] = {"onboarding_done": "true"}
    if llm_provider:
        prefs["llm_provider"] = llm_provider
    if default_model:
        prefs["default_model"] = default_model
    if project_name:
        prefs["project_name"] = project_name

    for key, value in prefs.items():
        asyncio.run(store.set_pref(key, value))

    # ── config.json: project infrastructure ──
    cfg = {k: v for k, v in load_global_config().items() if v is not _SENTINEL}
    changed = False
    if dashboard_url:
        cfg["dashboard_url"] = dashboard_url
        changed = True
    if agent_engine:
        cfg["agent_engine"] = agent_engine
        changed = True
    if changed:
        save_global_config(cfg)

    return {
        "saved": True,
        "sqlite_prefs": prefs,
        "config_json_updated": changed,
    }


def is_onboarding_complete() -> bool:
    """Return True if the onboarding wizard has been completed.

    Detection: checks ``onboarding_done`` in SQLite user_prefs.
    Falls back to legacy detection (``project_name`` in config.json)
    for backward compatibility with existing installations.
    """
    import asyncio

    try:
        from beddel.adapters.index_store import IndexStore

        store = IndexStore()
        value = asyncio.run(store.get_pref("onboarding_done"))
        if value == "true":
            return True
    except Exception:  # noqa: BLE001
        pass

    # Legacy fallback: config.json project_name
    cfg = load_global_config()
    return cfg.get("project_name", _SENTINEL) is not _SENTINEL


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


def resolve_dev_mode() -> bool:
    """Return whether the CLI should operate in dev mode.

    Resolution order (first explicit value wins):
    1. ``.beddel.json`` ``dev`` key
    2. ``~/.config/beddel/config.json`` ``dev`` key
    3. Default: ``True`` (dev mode)
    """
    # 1. Project-local
    project_cfg_path = find_project_config()
    if project_cfg_path is not None:
        cfg = load_project_config(project_cfg_path)
        if cfg["dev"] is not _SENTINEL:
            return bool(cfg["dev"])

    # 2. Global
    global_cfg = load_global_config()
    if global_cfg["dev"] is not _SENTINEL:
        return bool(global_cfg["dev"])

    # 3. Default — dev mode
    return True


def resolve_dashboard_url() -> str:
    """Return the dashboard URL to connect to.

    Resolution order (first explicit value wins):
    1. ``.beddel.json`` ``dashboard_url`` key
    2. ``~/.config/beddel/config.json`` ``dashboard_url`` key
    3. Default: ``http://localhost:3000`` if dev mode,
       ``https://connect.beddel.com.br`` if remote mode.
    """
    # 1. Project-local
    project_cfg_path = find_project_config()
    if project_cfg_path is not None:
        cfg = load_project_config(project_cfg_path)
        if cfg["dashboard_url"] is not _SENTINEL:
            return str(cfg["dashboard_url"])

    # 2. Global
    global_cfg = load_global_config()
    if global_cfg["dashboard_url"] is not _SENTINEL:
        return str(global_cfg["dashboard_url"])

    # 3. Default — depends on dev mode
    if resolve_dev_mode():
        return _DASHBOARD_URL_DEV
    return _DASHBOARD_URL_REMOTE


def resolve_agent_engine_url() -> str | None:
    """Return the Agent Engine resource URL, or ``None`` if not configured.

    Resolution order (first explicit value wins):
    1. ``.beddel.json`` ``agent_engine`` key
    2. ``~/.config/beddel/config.json`` ``agent_engine`` key
    3. Default: ``None`` (use local execution)
    """
    # 1. Project-local
    project_cfg_path = find_project_config()
    if project_cfg_path is not None:
        cfg = load_project_config(project_cfg_path)
        if cfg["agent_engine"] is not _SENTINEL:
            return str(cfg["agent_engine"])

    # 2. Global
    global_cfg = load_global_config()
    if global_cfg["agent_engine"] is not _SENTINEL:
        return str(global_cfg["agent_engine"])

    # 3. Default — no Agent Engine
    return None


_LLM_PROVIDER_DEFAULT: str = "gemini"
"""Default LLM provider when none is configured."""


def resolve_llm_provider() -> str:
    """Return the preferred LLM provider kit name.

    When multiple ``ILLMProvider`` kits are discovered, this value
    determines which one is selected instead of the previous
    "last-discovered wins" behavior.

    Resolution order (first explicit value wins):
    1. ``user_prefs`` table in ``index.db`` (key: ``llm_provider``)
    2. ``.beddel.json`` ``llm_provider`` key
    3. ``~/.config/beddel/config.json`` ``llm_provider`` key
    4. Default: ``"gemini"``

    If ``index.db`` is missing, corrupt, or any error occurs reading
    user_prefs, the function silently falls through to the config layers.
    """
    # 0. user_prefs (index.db)
    try:
        import asyncio

        from beddel.adapters.index_store import IndexStore

        pref = asyncio.run(IndexStore().get_pref("llm_provider"))
        if pref is not None:
            return pref
    except Exception:
        pass

    # 1. Project-local
    project_cfg_path = find_project_config()
    if project_cfg_path is not None:
        cfg = load_project_config(project_cfg_path)
        if cfg["llm_provider"] is not _SENTINEL:
            return str(cfg["llm_provider"])

    # 2. Global
    global_cfg = load_global_config()
    if global_cfg["llm_provider"] is not _SENTINEL:
        return str(global_cfg["llm_provider"])

    # 3. Default
    return _LLM_PROVIDER_DEFAULT


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
