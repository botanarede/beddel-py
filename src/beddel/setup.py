"""Public setup function for Python API users to activate kit paths."""

from __future__ import annotations

import sys
from pathlib import Path


def setup() -> None:
    """Activate kit paths so kit modules are importable.

    Call this before importing any kit module (e.g., ``beddel_provider_litellm``).
    Safe to call multiple times (idempotent).

    Example::

        import beddel
        beddel.setup()
        from beddel_provider_litellm.adapter import LiteLLMAdapter
    """
    from beddel.kits import BUNDLED_KITS_PATH

    # Bundled kits shipped inside the package
    if BUNDLED_KITS_PATH.is_dir():
        for kit_dir in BUNDLED_KITS_PATH.iterdir():
            kit_src = kit_dir / "src"
            if kit_src.is_dir() and str(kit_src) not in sys.path:
                sys.path.insert(0, str(kit_src))

    # Project-local kits (cwd/kits/)
    kits_dir = Path.cwd() / "kits"
    if kits_dir.is_dir():
        for kit_dir in kits_dir.iterdir():
            kit_src = kit_dir / "src"
            if kit_src.is_dir() and str(kit_src) not in sys.path:
                sys.path.insert(0, str(kit_src))
