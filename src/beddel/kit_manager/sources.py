"""Kit source management — download and install kits from git.

Supports two modes:
- manifest: download only kit.yaml (lightweight, no python/ modules)
- full: git sparse-checkout of kit.yaml + python/ tree
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

KITS_GIT_URL = "https://github.com/botanarede/beddel.git"
"""Git URL for sparse-checkout clone of kit sources."""

KITS_GITHUB_BASE = "https://raw.githubusercontent.com/botanarede/beddel/main/kits"
"""Base URL for downloading kit manifests (fallback mode)."""


def _check_git_available() -> bool:
    """Check if git is available on PATH."""
    try:
        subprocess.run(["git", "--version"], capture_output=True, check=True)
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


def install_kit(source: str, target_dir: Path, mode: str = "manifest") -> Path:
    """Install a kit from the beddel repository.

    Args:
        source: Short kit name (resolved against botanarede/beddel@main under kits/).
        target_dir: Directory where the kit will be installed (kit_name subdirectory).
        mode: Installation mode:
            - "manifest": download only kit.yaml via urllib (lightweight)
            - "full": git sparse-checkout of kit.yaml + python/ tree

    Returns:
        Path to the installed kit directory.

    Raises:
        RuntimeError: If git is not available (full mode) or download failed.
    """
    kit_name = source
    kit_dir = target_dir / kit_name

    # Already present with full modules — skip
    if kit_dir.exists() and (kit_dir / "kit.yaml").exists():
        if mode == "full" and (kit_dir / "python").is_dir():
            logger.info("Kit '%s' already installed (full)", kit_name)
            return kit_dir
        if mode == "manifest":
            logger.info("Kit '%s' already installed (manifest)", kit_name)
            return kit_dir

    if mode == "full":
        return _install_full(kit_name, target_dir)
    else:
        return _install_manifest(kit_name, target_dir)


def _install_full(kit_name: str, target_dir: Path) -> Path:
    """Install kit via git sparse-checkout (kit.yaml + python/ tree).

    Raises:
        RuntimeError: If git is unavailable or sparse-checkout fails.
    """
    if not _check_git_available():
        raise RuntimeError(
            "git is required for full kit installation. See: https://git-scm.com/downloads"
        )

    sparse_paths = [
        f"kits/{kit_name}/kit.yaml",
        f"kits/{kit_name}/python",
    ]

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
            raise RuntimeError(f"git clone failed for kit '{kit_name}': {result.stderr[:300]}")

        # Set sparse-checkout paths (--no-cone allows file + directory patterns)
        result = subprocess.run(
            ["git", "-C", tmpdir, "sparse-checkout", "set", "--no-cone", *sparse_paths],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"git sparse-checkout failed for kit '{kit_name}': {result.stderr[:300]}"
            )

        # Copy kit to target directory
        src = Path(tmpdir) / "kits" / kit_name
        if not src.is_dir():
            raise RuntimeError(f"Kit '{kit_name}' not found in repository after sparse-checkout")

        target_dir.mkdir(parents=True, exist_ok=True)
        dest = target_dir / kit_name
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(src, dest)

        return dest
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _install_manifest(kit_name: str, target_dir: Path) -> Path:
    """Install kit manifest only via urllib (no python/ modules)."""
    import urllib.request

    target_dir.mkdir(parents=True, exist_ok=True)
    kit_dir = target_dir / kit_name
    kit_dir.mkdir(parents=True, exist_ok=True)

    manifest_url = f"{KITS_GITHUB_BASE}/{kit_name}/kit.yaml"
    try:
        with urllib.request.urlopen(manifest_url, timeout=30) as resp:
            manifest_content = resp.read()
    except Exception as exc:
        raise RuntimeError(f"Failed to download manifest for '{kit_name}': {exc}") from exc

    (kit_dir / "kit.yaml").write_bytes(manifest_content)
    return kit_dir
