"""Shared pytest fixtures for Beddel SDK tests.

Kits are never put on ``sys.path``. Kit-backed test modules skip through
``pytest.importorskip`` when the kit or its third-party packages are absent.
"""

from __future__ import annotations

import pytest


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
