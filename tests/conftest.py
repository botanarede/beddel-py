"""Shared pytest fixtures for Beddel SDK tests.

Adds all kit source directories to ``sys.path`` at test bootstrap so that
kit module imports (e.g. ``from beddel_provider_litellm.adapter import ...``)
resolve without editable installs.
"""

from __future__ import annotations

import sys
from pathlib import Path

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

_KIT_DIRS = [
    "agent-openclaw-kit",
    "agent-claude-kit",
    "agent-codex-kit",
    "agent-kiro-kit",
    "provider-litellm-kit",
    "observability-otel-kit",
    "observability-langfuse-kit",
    "protocol-mcp-kit",
    "auth-github-kit",
    "serve-fastapi-kit",
    "tools-http-kit",
    "tools-file-kit",
    "tools-shell-kit",
    "tools-gates-kit",
    "provider-gemini-kit",
    "bridge-adk-kit",
    "ag-ui-kit",
]


def _resolve_kit_test_src(kit_dir: Path) -> Path | None:
    """Resolve kit source dir: python/ first, then src/ fallback."""
    python_dir = kit_dir / "python"
    if python_dir.is_dir():
        return python_dir
    src_dir = kit_dir / "src"
    if src_dir.is_dir():
        return src_dir
    return None


for _kit in _KIT_DIRS:
    _kit_path = _KITS_BASE / _kit
    _kit_src_dir = _resolve_kit_test_src(_kit_path)
    if _kit_src_dir:
        _kit_src = str(_kit_src_dir)
        if _kit_src not in sys.path:
            sys.path.insert(0, _kit_src)
