"""Shared pytest fixtures for Beddel SDK tests.

Adds all kit ``src/`` directories to ``sys.path`` at test bootstrap so that
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

# Kits live at: <project_root>/repo/kits/<kit>/src/
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
]

for _kit in _KIT_DIRS:
    _kit_src = str(_KITS_BASE / _kit / "src")
    if _kit_src not in sys.path:
        sys.path.insert(0, _kit_src)

# Inline kits live at: <project_root>/src/beddel-py/src/beddel/kits/<kit>/src/
_INLINE_KITS_BASE = _PROJECT_ROOT / "src" / "beddel-py" / "src" / "beddel" / "kits"

_INLINE_KIT_DIRS = [
    "ag-ui-kit",
]

for _kit in _INLINE_KIT_DIRS:
    _kit_src = str(_INLINE_KITS_BASE / _kit / "src")
    if _kit_src not in sys.path:
        sys.path.insert(0, _kit_src)
