"""beddel init — first-run setup command.

Provisions SQLite, asks for kits directory, installs required kits,
and saves preferences. Designed to work with minimal dependencies
(only pydantic, pyyaml, click).
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
"""User-level config directory (only stores index.db)."""

DEFAULT_KITS_DIR = BEDDEL_DATA_DIR / "kits"
"""Default kits directory. Can be changed later in the onboarding wizard."""


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


def download_kit(kit_name: str, kits_dir: Path) -> Path:
    """Download a kit from GitHub to the kits directory.

    Args:
        kit_name: Name of the kit.
        kits_dir: Target directory for kit installation.

    Returns:
        Path to the kit directory.
    """
    kit_dir = kits_dir / kit_name
    if kit_dir.exists() and (kit_dir / "kit.yaml").exists():
        click.echo(f"  ✓ Kit '{kit_name}' already present")
        return kit_dir

    kits_dir.mkdir(parents=True, exist_ok=True)
    manifest_url = f"{KITS_GITHUB_BASE}/{kit_name}/kit.yaml"
    click.echo(f"  ↓ Downloading {kit_name}...")

    try:
        with urllib.request.urlopen(manifest_url, timeout=30) as resp:
            manifest_content = resp.read()
    except Exception as exc:
        raise click.ClickException(
            f"Failed to download {manifest_url}: {exc}"
        ) from exc

    kit_dir.mkdir(parents=True, exist_ok=True)
    (kit_dir / "kit.yaml").write_bytes(manifest_content)
    click.echo(f"  ✓ Kit '{kit_name}' saved")
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
        """INSERT OR REPLACE INTO installed_kits (name, version, path, status)
           VALUES (?, ?, ?, 'installed')""",
        (kit_name, version, str(kit_path)),
    )
    conn.commit()
    conn.close()


def install_required_kits(db_path: Path, kits_dir: Path) -> bool:
    """Install all required kits.

    Returns:
        True if all kits installed successfully.
    """
    all_ok = True
    for kit_info in REQUIRED_KITS:
        kit_name = kit_info["name"]
        click.echo(f"\n  [{kit_name}] — {kit_info['reason']}")

        kit_path = download_kit(kit_name, kits_dir)

        if not install_kit_deps(kit_name, kit_info["pip_extras"]):
            all_ok = False
            continue

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
        click.echo("\nStep 2/3: Installing kits...")
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
