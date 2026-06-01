"""beddel init — first-run setup command.

Provisions SQLite, asks for kits directory, installs required kits,
and saves preferences. Designed to work with minimal dependencies
(only pydantic, pyyaml, click).
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
import tempfile
import urllib.request
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
        "pip_extras": "fastapi>=0.100,uvicorn>=0.20,sse-starlette>=1.6",
    },
    {
        "name": "ag-ui-kit",
        "reason": "A2UI interactive surfaces for onboarding",
        "pip_extras": "ag-ui-protocol>=0.1",
    },
    {
        "name": "provider-litellm-kit",
        "reason": "Multi-provider LLM adapter (Gemini, OpenAI, etc.)",
        "pip_extras": "litellm>=1.40",
    },
]
"""Kits required for the onboarding wizard to function."""

BEDDEL_DATA_DIR = Path.home() / ".config" / "beddel"
"""User-level config directory (only stores index.db)."""

DEFAULT_KITS_DIR = BEDDEL_DATA_DIR / "kits"
"""Default kits directory. Can be changed later in the onboarding wizard."""


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

        # Set sparse-checkout paths
        result = subprocess.run(
            ["git", "-C", tmpdir, "sparse-checkout", "set", *sparse_paths],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            logger.warning("git sparse-checkout failed: %s", result.stderr[:300])
            return False

        # Copy each kit to the target directory
        kits_dir.mkdir(parents=True, exist_ok=True)
        for name in kit_names:
            src = Path(tmpdir) / "kits" / name
            dest = kits_dir / name
            if src.is_dir():
                if dest.exists():
                    shutil.rmtree(dest)
                shutil.copytree(src, dest)

        return True
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# SQLite provisioning
# ---------------------------------------------------------------------------


def provision_sqlite() -> Path:
    """Create the SQLite database if it doesn't exist.

    Returns:
        Path to the database file.

    Raises:
        click.ClickException: If the database already exists.
    """
    import sqlite3

    BEDDEL_DATA_DIR.mkdir(parents=True, exist_ok=True)
    db_path = BEDDEL_DATA_DIR / "index.db"

    if db_path.exists():
        raise click.ClickException(
            f"Database already exists: {db_path}\n"
            "  Beddel is already initialized. To re-initialize:\n"
            f"  rm {db_path}"
        )

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


def install_kit_deps(kit_name: str, pip_extras: str) -> bool:
    """Install pip dependencies for a kit.

    Returns:
        True if installation succeeded.
    """
    packages = [p.strip() for p in pip_extras.split(",") if p.strip()]
    if not packages:
        return True

    click.echo(f"  ⚙ Installing: {', '.join(packages)}")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "--quiet", *packages],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        click.echo(f"  ✗ Failed: {result.stderr[:200]}", err=True)
        return False

    click.echo("  ✓ Deps OK")
    return True


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


def install_required_kits(db_path: Path, kits_dir: Path) -> bool:
    """Install all required kits via git sparse-checkout (with urllib fallback).

    Returns:
        True if all kits installed successfully.
    """
    kit_names = [k["name"] for k in REQUIRED_KITS]

    # Check which kits already have both kit.yaml AND python/
    kits_to_download = []
    for name in kit_names:
        kit_dir = kits_dir / name
        if kit_dir.exists() and (kit_dir / "kit.yaml").exists() and (kit_dir / "python").is_dir():
            click.echo(f"\n  ✓ Kit '{name}' already present (with modules)")
        else:
            kits_to_download.append(name)

    # Download missing kits via git sparse-checkout
    git_success = False
    if kits_to_download:
        if _check_git_available():
            click.echo(f"\n  ↓ Cloning kit sources via git ({len(kits_to_download)} kits)...")
            git_success = _download_kits_via_git(kits_to_download, kits_dir)
            if git_success:
                click.echo("  ✓ Git sparse-checkout complete")
            else:
                click.echo(
                    "  ⚠ git clone failed; falling back to manifest-only download.\n"
                    "    Kit modules will NOT be importable until you run: "
                    "beddel kit install <kit-name>",
                    err=True,
                )
        else:
            raise click.ClickException(
                "beddel init requires git. Install git and try again.\n"
                "  See: https://git-scm.com/downloads"
            )

    # Fallback: download manifests only for kits that git didn't provide
    if kits_to_download and not git_success:
        for name in kits_to_download:
            download_kit(name, kits_dir)

    # Install pip deps and register each kit
    all_ok = True
    for kit_info in REQUIRED_KITS:
        kit_name = kit_info["name"]
        kit_path = kits_dir / kit_name
        click.echo(f"\n  [{kit_name}] — {kit_info['reason']}")

        if not install_kit_deps(kit_name, kit_info["pip_extras"]):
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
# CLI command
# ---------------------------------------------------------------------------


def register_init_command(cli: Any) -> None:
    """Register the 'init' command on the CLI group."""

    @cli.command()
    @click.option("--yes", "-y", is_flag=True, help="Skip confirmation.")
    def init(*, yes: bool) -> None:
        """Initialize Beddel — provision database and install required kits.

        First command after `pip install beddel`. Provisions SQLite,
        installs required kits, saves preferences.
        Then run `beddel setup` for the interactive onboarding wizard.
        """
        kits_dir = DEFAULT_KITS_DIR

        click.echo()
        click.echo("🔧 Beddel Init")
        click.echo("=" * 40)
        click.echo()
        click.echo("  ℹ Requires: git (for kit source download)")
        click.echo(f"  Kits: {kits_dir}")
        click.echo("  Required:")
        for kit_info in REQUIRED_KITS:
            click.echo(f"    • {kit_info['name']}")
        click.echo()

        if not yes and not click.confirm("Proceed?", default=True):
            click.echo("Aborted.")
            raise SystemExit(0)

        click.echo()

        # Step 1: Provision SQLite
        click.echo("Step 1/3: Provisioning SQLite...")
        db_path = provision_sqlite()

        # Step 2: Install required kits
        click.echo("\nStep 2/3: Installing kits (requires git)...")
        if not install_required_kits(db_path, kits_dir):
            click.echo("\n⚠ Some kits failed. Run 'beddel init' again.", err=True)
            raise SystemExit(1)

        # Step 3: Save preferences
        click.echo("\nStep 3/3: Saving preferences...")
        save_pref(db_path, "kits_path", str(kits_dir))
        save_pref(db_path, "llm_provider", "litellm")
        save_pref(db_path, "initialized", "true")

        click.echo()
        click.echo("=" * 40)
        click.echo("✅ Beddel initialized!")
        click.echo()
        click.echo("Next: export GEMINI_API_KEY='...' && beddel setup")
        click.echo()
