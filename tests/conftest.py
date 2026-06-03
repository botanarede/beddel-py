"""Shared pytest fixtures for Beddel SDK tests.

Adds all kit source directories to ``sys.path`` at test bootstrap so that
kit module imports (e.g. ``from beddel_provider_litellm.adapter import ...``)
resolve without editable installs.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Kit sys.path bootstrap (ADR-0008, Story 5.1.1 Task 5)
# ---------------------------------------------------------------------------
# conftest.py lives at: <project_root>/src/beddel-py/tests/conftest.py
#   parents[0] = tests/
#   parents[1] = beddel-py/
#   parents[2] = src/
#   parents[3] = <project_root>
_PROJECT_ROOT = Path(__file__).resolve().parents[3]

# Kits live at: <project_root>/repo/kits/<kit>/{python|src}/
# (moved from <project_root>/kits/ during kit ecosystem restructure)
_KITS_BASE = _PROJECT_ROOT / "repo" / "kits"

# Dynamic discovery: add python/ (or src/) directory of every kit that has one
if _KITS_BASE.is_dir():
    for _kit_dir in sorted(_KITS_BASE.iterdir()):
        if not _kit_dir.is_dir():
            continue
        # Prefer python/ layout, fall back to src/
        _kit_python = _kit_dir / "python"
        _kit_src_alt = _kit_dir / "src"
        _kit_src_dir = (
            _kit_python
            if _kit_python.is_dir()
            else _kit_src_alt
            if _kit_src_alt.is_dir()
            else None
        )
        if _kit_src_dir and str(_kit_src_dir) not in sys.path:
            sys.path.insert(0, str(_kit_src_dir))


# ---------------------------------------------------------------------------
# Integration marker — opt-in tests that need network/git (skipped by default)
# ---------------------------------------------------------------------------
def pytest_addoption(parser: pytest.Parser) -> None:
    """Register the ``--run-integration`` opt-in flag."""
    parser.addoption(
        "--run-integration",
        action="store_true",
        default=False,
        help="Run integration tests that require network/git access.",
    )


def pytest_configure(config: pytest.Config) -> None:
    """Register the ``integration`` marker."""
    config.addinivalue_line(
        "markers",
        "integration: requires network/git; opt-in via --run-integration.",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip ``integration``-marked tests unless ``--run-integration`` is given."""
    if config.getoption("--run-integration"):
        return
    skip_marker = pytest.mark.skip(reason="needs --run-integration")
    for item in items:
        if item.get_closest_marker("integration") is not None:
            item.add_marker(skip_marker)
