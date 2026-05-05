"""beddel init — first-run setup command.

Provisions SQLite, installs required kits, and launches the onboarding wizard.
Designed to work with minimal dependencies (only pydantic, pyyaml, click).
"""

from __future__ import annotations

import logging
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Any

import click

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

KITS_GITHUB_BASE = "https://raw.githubusercontent.com/botanarede/beddel/main/kits"
"""Base URL for downloading kit manifests and source from GitHub."""

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
"""User-level config directory."""

KITS_INSTALL_DIR = BEDDEL_DATA_DIR / "kits"
"""Directory where downloaded kits are stored."""


# ---------------------------------------------------------------------------
# SQLite provisioning
# ---------------------------------------------------------------------------


def provision_sqlite() -> Path:
    """Create the SQLite database if it doesn't exist.

    Returns:
        Path to the database file.

    Raises:
        click.ClickException: If the database already exists (init already ran).
    """
    import sqlite3

    BEDDEL_DATA_DIR.mkdir(parents=True, exist_ok=True)
    db_path = BEDDEL_DATA_DIR / "index.db"

    if db_path.exists():
        raise click.ClickException(
            f"Database already exists: {db_path}\n"
            "  Beddel is already initialized. If you want to re-initialize,\n"
            f"  delete the database first: rm {db_path}"
        )

    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """CREATE TABLE user_prefs (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )"""
    )
    conn.execute(
        """CREATE TABLE installed_kits (
            name TEXT PRIMARY KEY,
            version TEXT NOT NULL,
            path TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'installed',
            installed_at TEXT NOT NULL DEFAULT (datetime('now'))
        )"""
    )
    conn.commit()
    conn.close()
    click.echo(f"  ✓ SQLite provisioned: {db_path}")
    return db_path


# ---------------------------------------------------------------------------
# Kit installation
# ---------------------------------------------------------------------------


def download_kit(kit_name: str) -> Path:
    """Locate a kit — first check bundled kits, then download from GitHub.

    Bundled kits ship inside the beddel package at
    ``beddel/kits/{kit_name}/``. If not found locally, attempts to
    download from GitHub.

    Args:
        kit_name: Name of the kit (e.g. 'serve-fastapi-kit').

    Returns:
        Path to the kit directory.
    """
    # Check bundled kits first
    try:
        from beddel.kits import BUNDLED_KITS_PATH

        bundled = BUNDLED_KITS_PATH / kit_name
        if bundled.exists() and (bundled / "kit.yaml").exists():
            click.echo(f"  ✓ Kit '{kit_name}' found (bundled)")
            return bundled
    except ImportError:
        pass

    # Check if already downloaded
    kit_dir = KITS_INSTALL_DIR / kit_name
    if kit_dir.exists() and (kit_dir / "kit.yaml").exists():
        click.echo(f"  ✓ Kit '{kit_name}' already downloaded")
        return kit_dir

    # Download from GitHub
    KITS_INSTALL_DIR.mkdir(parents=True, exist_ok=True)
    manifest_url = f"{KITS_GITHUB_BASE}/{kit_name}/kit.yaml"
    click.echo(f"  ↓ Downloading {kit_name}/kit.yaml...")

    try:
        with urllib.request.urlopen(manifest_url, timeout=30) as resp:
            manifest_content = resp.read()
    except Exception as exc:
        raise click.ClickException(
            f"Failed to download kit manifest from {manifest_url}: {exc}"
        ) from exc

    kit_dir.mkdir(parents=True, exist_ok=True)
    (kit_dir / "kit.yaml").write_bytes(manifest_content)
    click.echo(f"  ✓ Kit '{kit_name}' manifest saved")
    return kit_dir


def install_kit_deps(kit_name: str, pip_extras: str) -> bool:
    """Install pip dependencies for a kit.

    Args:
        kit_name: Kit name for logging.
        pip_extras: Comma-separated pip packages to install.

    Returns:
        True if installation succeeded.
    """
    packages = [p.strip() for p in pip_extras.split(",") if p.strip()]
    if not packages:
        return True

    click.echo(f"  ⚙ Installing deps for '{kit_name}': {', '.join(packages)}")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "--quiet", *packages],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        click.echo(f"  ✗ pip install failed: {result.stderr[:200]}", err=True)
        return False

    click.echo(f"  ✓ Dependencies installed for '{kit_name}'")
    return True


def register_kit_in_db(db_path: Path, kit_name: str, kit_path: Path, version: str = "0.1.0") -> None:
    """Register an installed kit in the SQLite database.

    Args:
        db_path: Path to the SQLite database.
        kit_name: Kit name.
        kit_path: Path where the kit is installed.
        version: Kit version string.
    """
    import sqlite3

    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """INSERT OR REPLACE INTO installed_kits (name, version, path, status)
           VALUES (?, ?, ?, 'installed')""",
        (kit_name, version, str(kit_path)),
    )
    conn.commit()
    conn.close()


def install_required_kits(db_path: Path) -> bool:
    """Install all required kits for the onboarding wizard.

    Args:
        db_path: Path to the SQLite database.

    Returns:
        True if all kits installed successfully.
    """
    all_ok = True
    for kit_info in REQUIRED_KITS:
        kit_name = kit_info["name"]
        click.echo(f"\n  [{kit_name}] — {kit_info['reason']}")

        # Download manifest
        kit_path = download_kit(kit_name)

        # Install pip deps
        if not install_kit_deps(kit_name, kit_info["pip_extras"]):
            all_ok = False
            continue

        # Register in DB
        register_kit_in_db(db_path, kit_name, kit_path)

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
    @click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt.")
    def init(*, yes: bool) -> None:
        """Initialize Beddel — provision database and install required kits.

        This is the first command to run after `pip install beddel`.
        It provisions the SQLite database, installs required kits
        (FastAPI server, A2UI, LLM provider), and writes the initial config.

        After init completes, run `beddel setup` to launch the interactive
        onboarding wizard in your browser.
        """
        click.echo()
        click.echo("🔧 Beddel Init")
        click.echo("=" * 40)
        click.echo()
        click.echo("This will:")
        click.echo("  1. Provision SQLite database (~/.config/beddel/index.db)")
        click.echo("  2. Install required kits:")
        for kit_info in REQUIRED_KITS:
            click.echo(f"     • {kit_info['name']} — {kit_info['reason']}")
        click.echo("  3. Write initial config (~/.config/beddel/config.json)")
        click.echo()

        if not yes:
            if not click.confirm("Proceed?", default=True):
                click.echo("Aborted.")
                raise SystemExit(0)

        click.echo()

        # Step 1: Provision SQLite
        click.echo("Step 1/3: Provisioning SQLite...")
        db_path = provision_sqlite()

        # Step 2: Install required kits
        click.echo("\nStep 2/3: Installing required kits...")
        if not install_required_kits(db_path):
            click.echo("\n⚠ Some kits failed to install. Run 'beddel init' again to retry.", err=True)
            raise SystemExit(1)

        # Step 3: Write config
        click.echo("\nStep 3/3: Saving preferences...")
        save_pref(db_path, "llm_provider", "litellm")
        save_pref(db_path, "kits_path", str(KITS_INSTALL_DIR))
        save_pref(db_path, "initialized", "true")

        click.echo()
        click.echo("=" * 40)
        click.echo("✅ Beddel initialized successfully!")
        click.echo()
        click.echo("Next steps:")
        click.echo("  1. Authenticate with Google Cloud (for Gemini):")
        click.echo("     gcloud auth application-default login")
        click.echo()
        click.echo("  2. Set your Gemini API key (alternative to ADC):")
        click.echo("     export GEMINI_API_KEY='your-key-here'")
        click.echo()
        click.echo("  3. Launch the onboarding wizard:")
        click.echo("     beddel setup")
        click.echo()
