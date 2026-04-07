"""Tests for the public ``beddel.setup()`` function."""

from __future__ import annotations

import sys


class TestSetupImportable:
    """beddel.setup() is importable and callable."""

    def test_setup_importable(self) -> None:
        import beddel

        assert callable(beddel.setup)

    def test_setup_callable_no_error(self) -> None:
        import beddel

        # Should not raise
        beddel.setup()


class TestSetupAddsKitPaths:
    """setup() adds bundled kit src/ directories to sys.path."""

    def test_setup_adds_bundled_kit_paths(self) -> None:
        from beddel.kits import BUNDLED_KITS_PATH
        from beddel.setup import setup

        setup()

        if BUNDLED_KITS_PATH.is_dir():
            for kit_dir in BUNDLED_KITS_PATH.iterdir():
                kit_src = kit_dir / "src"
                if kit_src.is_dir():
                    assert str(kit_src) in sys.path


class TestSetupIdempotent:
    """Calling setup() twice does not duplicate paths."""

    def test_setup_idempotent(self) -> None:
        from beddel.setup import setup

        setup()
        paths_after_first = list(sys.path)

        setup()
        paths_after_second = list(sys.path)

        assert paths_after_first == paths_after_second
