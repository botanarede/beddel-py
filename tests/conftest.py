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
]

for _kit in _KIT_DIRS:
    _kit_src = str(_PROJECT_ROOT / "kits" / _kit / "src")
    if _kit_src not in sys.path:
        sys.path.insert(0, _kit_src)
