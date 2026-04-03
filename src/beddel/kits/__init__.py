"""Bundled kit manifests shipped with the ``beddel`` package.

The :data:`BUNDLED_KITS_PATH` constant points to this directory so that
:func:`~beddel.tools.kits.discover_kits` can scan it at runtime.
"""

from __future__ import annotations

from pathlib import Path

BUNDLED_KITS_PATH: Path = Path(__file__).parent
