"""beddel init — first-run setup command.

Provisions SQLite, asks for kits directory, installs required kits,
and saves preferences. Designed to work with minimal dependencies
(only pydantic, pyyaml, click).
"""

from __future__ import annotations

import importlib.util
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import click

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

KITS_GITHUB_BASE = "https://raw.githubusercontent.com/botanarede/beddel/main/kits"
"""Base URL for downloading kit manifests (fallback mode)."""

KITS_GIT_URL = "https://github.com/botanarede/beddel.git"
"""Git URL for sparse-checkout clone of kit sources."""

REQUIRED_KITS: list[dict[str, str]] = [
    {
        "name": "serve-fastapi-kit",
        "reason": "HTTP server for dashboard and A2UI",
    },
    {
        "name": "ag-ui-kit",
        "reason": "A2UI interactive surfaces for onboarding",
    },
]
"""Kits always installed regardless of provider choice."""

PROVIDER_KITS: dict[str, list[dict[str, str]]] = {
    "gemini": [
        {"name": "provider-gemini-kit", "reason": "Google Gemini LLM provider (ADC)"},
    ],
    "litellm": [
        {
            "name": "provider-litellm-kit",
            "reason": "Multi-provider LLM adapter (Gemini, OpenAI, etc.)",
        },
    ],
    "adk": [
        {"name": "bridge-adk-kit", "reason": "ADK Bridge for Agent Engine deploy"},
        {"name": "provider-gemini-kit", "reason": "Google Gemini LLM provider (ADC)"},
    ],
}
"""Provider-specific kits selected via --provider flag."""

BEDDEL_DATA_DIR = Path.home() / ".config" / "beddel"
"""User-level config directory (only stores index.db)."""

DEFAULT_KITS_DIR = BEDDEL_DATA_DIR / "kits"
"""Fallback kits directory, used only by the non-interactive ``--kits-dir`` default."""

PROVIDER_CHOICES: tuple[str, ...] = ("gemini", "litellm", "adk")
"""Selectable LLM providers.  No provider is pre-selected in the prompt."""


# ---------------------------------------------------------------------------
# Bootstrap state
# ---------------------------------------------------------------------------


def base_kits_present(provider: str | None = None) -> bool:
    """Return True when every kit the runner needs is present on disk.

    The onboarding wizard is served *by* these kits, so a provisioned
    database is not sufficient on its own — the kits must be installed
    as well.  This is the second half of the ``launch`` pre-flight.

    A provider kit is not optional: without one the runner has no LLM and
    every example flow with an ``llm`` step fails.  ``initialize`` always
    installs one, so its absence means the install never completed.  When
    *provider* is None the configured provider is resolved, so the check
    follows the choice the user actually made.
    """
    from beddel.cli.config import resolve_kits_paths, resolve_llm_provider

    kits_paths = resolve_kits_paths()
    if not kits_paths:
        return False

    if provider is None:
        provider = resolve_llm_provider()
    required = [k["name"] for k in REQUIRED_KITS + PROVIDER_KITS.get(provider, [])]
    for name in required:
        if not any((base / name / "kit.yaml").exists() for base in kits_paths):
            return False
    return True


def is_bootstrapped() -> bool:
    """Return True when both halves of the pre-flight are satisfied."""
    db_path = BEDDEL_DATA_DIR / "index.db"
    return db_path.exists() and base_kits_present()


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------


def _check_git_available() -> bool:
    """Check if git is available on PATH."""
    try:
        subprocess.run(["git", "--version"], capture_output=True, check=True)
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


def _download_kits_via_git(kit_names: list[str], kits_dir: Path) -> bool:
    """Download kits using git sparse-checkout (single clone for all kits).

    Returns True if successful, False if git clone failed.
    """
    sparse_paths: list[str] = []
    for name in kit_names:
        sparse_paths.append(f"kits/{name}/kit.yaml")
        sparse_paths.append(f"kits/{name}/python")

    tmpdir = tempfile.mkdtemp(prefix="beddel-kit-")
    try:
        # Clone with sparse filter
        result = subprocess.run(
            [
                "git",
                "clone",
                "--depth=1",
                "--filter=blob:none",
                "--sparse",
                "--branch",
                "main",
                KITS_GIT_URL,
                tmpdir,
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            logger.warning("git clone failed: %s", result.stderr[:300])
            return False

        # Set sparse-checkout paths (--no-cone allows file + directory patterns)
        result = subprocess.run(
            ["git", "-C", tmpdir, "sparse-checkout", "set", "--no-cone", *sparse_paths],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            logger.warning("git sparse-checkout failed: %s", result.stderr[:300])
            return False

        # Copy each kit to the target directory
        kits_dir.mkdir(parents=True, exist_ok=True)
        copied_any = False
        for name in kit_names:
            src = Path(tmpdir) / "kits" / name
            dest = kits_dir / name
            if src.is_dir():
                if dest.exists():
                    shutil.rmtree(dest)
                shutil.copytree(src, dest)
                copied_any = True

        if not copied_any:
            logger.warning("git sparse-checkout produced no kit directories")
            return False

        return True
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# SQLite provisioning
# ---------------------------------------------------------------------------


def provision_sqlite(*, force: bool = False) -> Path:
    """Create the SQLite database if it doesn't exist.

    If the database already exists and force=False, returns the existing
    path (idempotent). If force=True, deletes and recreates.

    Returns:
        Path to the database file.
    """
    import sqlite3

    BEDDEL_DATA_DIR.mkdir(parents=True, exist_ok=True)
    db_path = BEDDEL_DATA_DIR / "index.db"

    if db_path.exists():
        if force:
            db_path.unlink()
            click.echo(f"  ⟳ Removed existing database: {db_path}")
        else:
            click.echo(f"  ✓ SQLite already provisioned: {db_path}")
            return db_path

    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """CREATE TABLE user_prefs (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS kit_index (
            name TEXT PRIMARY KEY,
            version TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            category TEXT NOT NULL DEFAULT 'general',
            path TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            port TEXT NOT NULL DEFAULT '',
            discovered_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        )"""
    )
    conn.commit()
    conn.close()
    click.echo(f"  ✓ SQLite provisioned: {db_path}")
    return db_path


# ---------------------------------------------------------------------------
# Kit installation
# ---------------------------------------------------------------------------


def download_kit(kit_name: str, kits_dir: Path) -> Path:
    """Download a single kit manifest via urllib (fallback mode).

    Only downloads kit.yaml — python/ modules will NOT be available.

    Args:
        kit_name: Name of the kit.
        kits_dir: Target directory for kit installation.

    Returns:
        Path to the kit directory.
    """
    kit_dir = kits_dir / kit_name
    if kit_dir.exists() and (kit_dir / "kit.yaml").exists():
        if (kit_dir / "python").is_dir():
            click.echo(f"  ✓ Kit '{kit_name}' already present (with modules)")
        else:
            click.echo(f"  ✓ Kit '{kit_name}' already present (manifest only)")
        return kit_dir

    kits_dir.mkdir(parents=True, exist_ok=True)
    manifest_url = f"{KITS_GITHUB_BASE}/{kit_name}/kit.yaml"
    click.echo(f"  ↓ Downloading {kit_name} manifest...")

    try:
        with urllib.request.urlopen(manifest_url, timeout=30) as resp:
            manifest_content = resp.read()
    except Exception as exc:
        raise click.ClickException(f"Failed to download {manifest_url}: {exc}") from exc

    kit_dir.mkdir(parents=True, exist_ok=True)
    (kit_dir / "kit.yaml").write_bytes(manifest_content)
    click.echo(f"  ✓ Kit '{kit_name}' saved (manifest only)")
    return kit_dir


def resolve_install_command(packages: Sequence[str], *, quiet: bool = False) -> list[str]:
    """Build the command that installs ``packages`` into the running interpreter.

    ``uv`` is preferred when available because a uv-managed virtual environment
    does not necessarily contain ``pip``.  ``--python sys.executable`` is passed
    explicitly: ``uv pip install`` otherwise relies on ``VIRTUAL_ENV``, which is
    unset when the CLI is launched through the environment's console script.
    ``python -m pip`` remains the fallback so installations from PyPI, where uv
    is not present, keep working.

    Args:
        packages: Python requirement specifiers to install.
        quiet: Whether to suppress the installer's own progress output.

    Returns:
        The argument vector to execute.

    Raises:
        RuntimeError: If neither uv nor pip is available in this environment.
    """
    uv = shutil.which("uv")
    if uv:
        command = [uv, "pip", "install", "--python", sys.executable]
        if quiet:
            command.append("--quiet")
        return [*command, *packages]

    if importlib.util.find_spec("pip") is None:
        raise RuntimeError(
            f"No Python package installer available for interpreter "
            f"'{sys.executable}': neither 'uv' on PATH nor the 'pip' module. "
            f"Install uv, or use an environment that provides pip."
        )

    command = [sys.executable, "-m", "pip", "install"]
    if quiet:
        command.append("--quiet")
    return [*command, *packages]


def install_requirements(packages: Sequence[str], *, quiet: bool = False) -> bool:
    """Install Python package requirements into the running interpreter.

    Single installation path shared by every kit provisioning command.

    Args:
        packages: Python requirement specifiers to install.
        quiet: Whether to suppress the installer's own progress output.

    Returns:
        True if installation succeeded.
    """
    if not packages:
        return True

    click.echo(f"  ⚙ Installing: {', '.join(packages)}")
    try:
        command = resolve_install_command(packages, quiet=quiet)
    except RuntimeError as exc:
        click.echo(f"  ✗ Failed: {exc}", err=True)
        return False

    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        click.echo(f"  ✗ Failed: {result.stderr[:200]}", err=True)
        return False

    click.echo("  ✓ Deps OK")
    return True


def install_kit_deps(kit_name: str, pip_extras: str) -> bool:
    """Install the Python package requirements declared for a kit.

    Returns:
        True if installation succeeded.
    """
    packages = [p.strip() for p in pip_extras.split(",") if p.strip()]
    return install_requirements(packages, quiet=True)


def register_kit_in_db(
    db_path: Path, kit_name: str, kit_path: Path, version: str = "0.1.0"
) -> None:
    """Register an installed kit in the SQLite database."""
    import sqlite3

    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """INSERT OR REPLACE INTO kit_index
           (name, version, path)
           VALUES (?, ?, ?)""",
        (kit_name, version, str(kit_path)),
    )
    conn.commit()
    conn.close()


def install_required_kits(db_path: Path, kits_dir: Path, kits: list[dict[str, str]]) -> bool:
    """Install all required kits via kit_manager (full mode: kit.yaml + python/).

    Uses beddel.kit_manager.sources.install_kit with mode="full" to perform
    git sparse-checkout of the complete kit source including the python/ tree.

    Args:
        db_path: Path to the SQLite database.
        kits_dir: Target directory for kit installation.
        kits: List of kit dicts with 'name' and 'reason' keys.

    Returns:
        True if all kits installed successfully.
    """
    from beddel.kit_manager.sources import install_kit as _install_kit

    kit_names = [k["name"] for k in kits]

    # Install each kit via kit_manager (full mode)
    all_ok = True
    for kit_info in kits:
        kit_name = kit_info["name"]
        click.echo(f"\n  [{kit_name}] — {kit_info['reason']}")

        try:
            kit_path = _install_kit(kit_name, kits_dir, mode="full")
            if (kit_path / "python").is_dir():
                click.echo(f"  ✓ Kit '{kit_name}' installed (with modules)")
            else:
                click.echo(f"  ✓ Kit '{kit_name}' installed (manifest only)")
        except RuntimeError as exc:
            click.echo(f"  ✗ Kit '{kit_name}' failed: {exc}", err=True)
            # Fallback to manifest-only download
            try:
                download_kit(kit_name, kits_dir)
            except click.ClickException as fallback_exc:
                click.echo(f"  ✗ Fallback also failed: {fallback_exc}", err=True)
                all_ok = False
                continue

        kit_path = kits_dir / kit_name

        # Read deps from manifest (single source of truth)
        kit_yaml_path = kit_path / "kit.yaml"
        pip_deps: list[str] = []
        if kit_yaml_path.exists():
            import yaml

            with open(kit_yaml_path) as f:
                manifest_data = yaml.safe_load(f)
            targets = manifest_data.get("targets", {})
            py_target = targets.get("python", {})
            pip_deps = py_target.get("dependencies", [])

        if pip_deps and not install_kit_deps(kit_name, ",".join(pip_deps)):
            all_ok = False
            continue

        register_kit_in_db(db_path, kit_name, kit_path)

    # Summary: show which kits have python/ modules
    click.echo("\n  Kit status:")
    for name in kit_names:
        kit_dir = kits_dir / name
        if (kit_dir / "python").is_dir():
            click.echo(f"    ✓ {name} — modules available")
        else:
            click.echo(f"    ⚠ {name} — manifest only (run: beddel kit install {name})")

    return all_ok


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------


def save_pref(db_path: Path, key: str, value: str) -> None:
    """Save a user preference to SQLite."""
    import sqlite3

    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "INSERT OR REPLACE INTO user_prefs (key, value) VALUES (?, ?)",
        (key, value),
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Bootstrap: non-interactive core and interactive consent
# ---------------------------------------------------------------------------


def initialize(provider: str, kits_dir: Path, *, force: bool = False) -> None:
    """Provision the database, install kits and save preferences.

    This is the non-interactive core shared by ``beddel init`` and by the
    ``beddel launch`` consent prompt.  It performs no prompting: every
    decision arrives as an argument, so the caller owns consent.

    Args:
        provider: One of :data:`PROVIDER_CHOICES`.
        kits_dir: Directory the kits are installed into.
        force: Recreate the database instead of reusing it.

    Raises:
        SystemExit: If one or more kits could not be installed.
    """
    all_kits = REQUIRED_KITS + PROVIDER_KITS[provider]

    click.echo("Step 1/3: Provisioning SQLite...")
    db_path = provision_sqlite(force=force)

    click.echo("\nStep 2/3: Installing kits...")
    kit_names_needed = [k["name"] for k in all_kits]
    skip_download = False

    # BEDDEL_KIT_PATHS env var (dev environment override)
    env_kit_paths = os.environ.get("BEDDEL_KIT_PATHS", "")
    if env_kit_paths:
        for env_path_str in env_kit_paths.split(":"):
            env_path = Path(env_path_str.strip())
            if env_path.is_dir():
                present = [name for name in kit_names_needed if (env_path / name).is_dir()]
                if len(present) == len(kit_names_needed):
                    skip_download = True
                    click.echo(f"  ✓ All required kits found via BEDDEL_KIT_PATHS: {env_path}")
                    for kit_info in all_kits:
                        register_kit_in_db(db_path, kit_info["name"], env_path / kit_info["name"])
                    break

    # Configured kits_paths as fallback
    if not skip_download:
        from beddel.cli.config import resolve_kits_paths

        existing_kits_paths = resolve_kits_paths()
        if existing_kits_paths:
            first_path = existing_kits_paths[0]
            if first_path.is_dir():
                present = [name for name in kit_names_needed if (first_path / name).is_dir()]
                if len(present) == len(kit_names_needed):
                    skip_download = True
                    click.echo(f"  ✓ All required kits already present in {first_path}")
                    for kit_info in all_kits:
                        register_kit_in_db(db_path, kit_info["name"], first_path / kit_info["name"])

    if not skip_download and not install_required_kits(db_path, kits_dir, all_kits):
        click.echo("\n⚠ Some kits failed. Run 'beddel init' again.", err=True)
        raise SystemExit(1)

    # Remove a stale fallback kits directory when the kits came from elsewhere
    if force and skip_download and kits_dir.is_dir():
        import shutil as _shutil

        _shutil.rmtree(kits_dir, ignore_errors=True)
        click.echo(f"  ⟳ Removed stale local kits: {kits_dir}")

    click.echo("\nStep 3/3: Saving preferences...")
    save_pref(db_path, "llm_provider", provider)
    save_pref(db_path, "initialized", "true")


def _persist_kits_dir(kits_dir: Path) -> None:
    """Record the user's chosen kits directory as the configured path.

    The chosen directory *is* the consent: there is no implicit default,
    so discovery has nothing to fall back on until this is written.  A
    project-local ``.beddel.json`` already declaring ``kits_paths`` takes
    precedence over the global file and is therefore left untouched.
    """
    from beddel.cli.config import (
        _SENTINEL,
        find_project_config,
        load_global_config,
        load_project_config,
        save_global_config,
    )

    project_cfg_path = find_project_config()
    if project_cfg_path is not None and load_project_config(project_cfg_path)["kits_paths"]:
        click.echo(f"  ✓ Using kits_paths from {project_cfg_path}")
        return

    data = {k: v for k, v in load_global_config().items() if v is not _SENTINEL}
    data["kits_paths"] = [str(kits_dir)]
    save_global_config(data)
    click.echo(f"  ✓ Saved kits_paths: {kits_dir}")


def _stdin_is_tty() -> bool:
    """Return whether stdin is an interactive terminal.

    Named rather than inlined so the interactive branch stays reachable
    under test runners that replace ``sys.stdin`` after collection.
    """
    return sys.stdin.isatty()


def prompt_bootstrap() -> bool:
    """Ask for every setup decision, then bootstrap on an explicit yes.

    Nothing is written before the user accepts: the provider, the kits
    directory and the install itself are all confirmed up front, and the
    reasons for each kit are shown so the cost is visible.

    Returns:
        True when the environment was bootstrapped, False when the user
        declined (in which case nothing was written).

    Raises:
        SystemExit: When there is no TTY to prompt on, naming the
            non-interactive command instead.
    """
    if not _stdin_is_tty():
        click.echo("  ✗ Beddel is not set up, and there is no terminal to ask on.", err=True)
        click.echo(
            "    Run, choosing a provider and a kits directory:\n"
            "      beddel init --provider <"
            + "|".join(PROVIDER_CHOICES)
            + "> --kits-dir <DIR> --yes",
            err=True,
        )
        raise SystemExit(1)

    click.echo()
    click.echo("  Beddel is not set up yet. Three questions before anything is written.")
    click.echo()

    provider = click.prompt(
        "  1. LLM provider",
        type=click.Choice(PROVIDER_CHOICES, case_sensitive=False),
        show_choices=True,
    ).lower()

    kits_dir = Path(
        click.prompt("  2. Directory to keep kits in", type=str).strip()
    ).expanduser()

    all_kits = REQUIRED_KITS + PROVIDER_KITS[provider]
    click.echo()
    click.echo("  3. This will install, into that directory:")
    for kit_info in all_kits:
        click.echo(f"       • {kit_info['name']:22} — {kit_info['reason']}")
    click.echo("     …plus the Python packages each kit declares.")
    click.echo()

    if not click.confirm("  Proceed?", default=False):
        click.echo("  Aborted — nothing was written.")
        return False

    click.echo()
    kits_dir.mkdir(parents=True, exist_ok=True)
    _persist_kits_dir(kits_dir)
    initialize(provider, kits_dir)
    return True


# ---------------------------------------------------------------------------
# CLI command
# ---------------------------------------------------------------------------


def register_init_command(cli: Any) -> None:
    """Register the 'init' command on the CLI group."""

    @cli.command()
    @click.option("--yes", "-y", is_flag=True, help="Skip confirmation.")
    @click.option("--force", "-f", is_flag=True, help="Force re-initialization (recreates DB).")
    @click.option(
        "--provider",
        type=click.Choice(list(PROVIDER_CHOICES), case_sensitive=False),
        required=True,
        help="LLM provider to install.",
    )
    @click.option(
        "--kits-dir",
        type=click.Path(file_okay=False, path_type=Path),
        default=DEFAULT_KITS_DIR,
        show_default=True,
        help="Directory to install kits into.",
    )
    def init(*, yes: bool, force: bool, provider: str, kits_dir: Path) -> None:
        """Initialize Beddel — provision database and install required kits.

        The non-interactive path, for CI and scripted setup: every decision
        is a flag.  Interactive users can just run `beddel launch`, which
        asks the same questions before writing anything.  Idempotent by
        default; use --force to recreate the database.
        """
        provider = provider.lower()
        kits_dir = kits_dir.expanduser()
        all_kits = REQUIRED_KITS + PROVIDER_KITS[provider]

        click.echo()
        click.echo("🔧 Beddel Init")
        click.echo("=" * 40)
        click.echo()
        click.echo("  ℹ Requires: git (for kit source download)")
        click.echo(f"  Provider: {provider}")
        click.echo(f"  Kits: {kits_dir}")
        click.echo("  Required:")
        for kit_info in all_kits:
            click.echo(f"    • {kit_info['name']}")
        click.echo()

        if not yes and not click.confirm("Proceed?", default=True):
            click.echo("Aborted.")
            raise SystemExit(0)

        click.echo()
        kits_dir.mkdir(parents=True, exist_ok=True)
        _persist_kits_dir(kits_dir)
        initialize(provider, kits_dir, force=force)

        click.echo()
        click.echo("=" * 40)
        click.echo(f"✅ Beddel initialized! (provider: {provider})")
        click.echo()
        click.echo("Next: beddel launch")
        click.echo("Install additional kits: beddel kit install <name>")
        click.echo()
