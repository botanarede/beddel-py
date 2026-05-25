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

        # Should not raise (no-op when SQLite db doesn't exist)
        beddel.setup()


class TestSetupIdempotent:
    """Calling setup() twice does not duplicate paths."""

    def test_setup_idempotent(self) -> None:
        from beddel.setup import setup

        setup()
        paths_after_first = list(sys.path)

        setup()
        paths_after_second = list(sys.path)

        assert paths_after_first == paths_after_second


class TestResolveKitSrcDir:
    """_resolve_kit_src_dir resolves python/ or src/ subdirectory."""

    def test_python_dir(self, tmp_path) -> None:
        """Returns python/ path when it exists."""
        from beddel.setup import _resolve_kit_src_dir

        kit_dir = tmp_path / "my-kit"
        kit_dir.mkdir()
        (kit_dir / "python").mkdir()
        assert _resolve_kit_src_dir(kit_dir) == kit_dir / "python"

    def test_src_fallback(self, tmp_path) -> None:
        """Falls back to src/ when python/ doesn't exist."""
        from beddel.setup import _resolve_kit_src_dir

        kit_dir = tmp_path / "my-kit"
        kit_dir.mkdir()
        (kit_dir / "src").mkdir()
        assert _resolve_kit_src_dir(kit_dir) == kit_dir / "src"

    def test_neither(self, tmp_path) -> None:
        """Returns None when neither python/ nor src/ exist."""
        from beddel.setup import _resolve_kit_src_dir

        kit_dir = tmp_path / "my-kit"
        kit_dir.mkdir()
        assert _resolve_kit_src_dir(kit_dir) is None

    def test_python_wins_over_src(self, tmp_path) -> None:
        """Returns python/ when both python/ and src/ exist."""
        from beddel.setup import _resolve_kit_src_dir

        kit_dir = tmp_path / "my-kit"
        kit_dir.mkdir()
        (kit_dir / "python").mkdir()
        (kit_dir / "src").mkdir()
        assert _resolve_kit_src_dir(kit_dir) == kit_dir / "python"


class TestResolveKitsPath:
    """_resolve_kits_path reads from SQLite when available."""

    def test_returns_none_when_no_db(self, tmp_path, monkeypatch) -> None:
        """Returns None when index.db doesn't exist."""
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
        from beddel.setup import _resolve_kits_path

        result = _resolve_kits_path()
        assert result is None
