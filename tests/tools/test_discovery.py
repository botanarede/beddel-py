"""Unit tests for beddel.tools — @beddel_tool decorator and discover_builtin_tools()."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from beddel.tools import beddel_tool, discover_builtin_tools


class TestBeddelToolDecorator:
    """Tests for the @beddel_tool decorator."""

    def test_stores_metadata_on_function(self) -> None:
        @beddel_tool(name="my-tool", description="A test tool", category="test")
        def my_func() -> str:
            return "hello"

        meta: dict[str, str] = my_func._beddel_tool_meta  # type: ignore[attr-defined]
        assert meta == {
            "name": "my-tool",
            "description": "A test tool",
            "category": "test",
        }

    def test_decorated_function_remains_callable(self) -> None:
        @beddel_tool(name="callable-tool", description="desc", category="general")
        def adder(a: int, b: int) -> int:
            return a + b

        assert adder(2, 3) == 5

    def test_default_description_and_category(self) -> None:
        @beddel_tool(name="minimal")
        def noop() -> None:
            pass

        meta: dict[str, str] = noop._beddel_tool_meta  # type: ignore[attr-defined]
        assert meta["description"] == ""
        assert meta["category"] == "general"

    def test_returns_original_function_identity(self) -> None:
        def original() -> None:
            pass

        decorated = beddel_tool(name="id-check")(original)
        assert decorated is original


class TestDiscoverBuiltinTools:
    """Tests for discover_builtin_tools()."""

    def test_returns_dict(self) -> None:
        result = discover_builtin_tools()
        assert isinstance(result, dict)

    def test_returns_empty_when_no_submodules_have_tools(self) -> None:
        """No builtin tool submodules exist yet, so discovery returns empty."""
        result = discover_builtin_tools()
        assert result == {}

    def test_all_values_are_callable(self) -> None:
        result = discover_builtin_tools()
        for fn in result.values():
            assert callable(fn)


class TestDiscoverBuiltinToolsWithDummy:
    """Tests that verify the discovery mechanism works using a temporary module."""

    def test_discovers_tool_from_injected_submodule(self, tmp_path: Any, monkeypatch: Any) -> None:
        """Create a temporary submodule with a decorated tool and verify discovery."""
        import importlib
        import types

        # Arrange — create a fake beddel.tools.fake_tool module
        fake_mod = types.ModuleType("beddel.tools._test_fake")
        fake_mod.__package__ = "beddel.tools"

        @beddel_tool(name="fake-tool", description="A fake tool", category="test")
        def fake_fn() -> str:
            return "fake"

        fake_mod.fake_fn = fake_fn  # type: ignore[attr-defined]

        # We monkeypatch importlib.import_module to intercept our fake module
        real_import = importlib.import_module

        def patched_import(name: str, package: str | None = None) -> types.ModuleType:
            if name == "beddel.tools._test_fake":
                return fake_mod
            return real_import(name, package)

        monkeypatch.setattr(importlib, "import_module", patched_import)

        # Also patch pkgutil.iter_modules to yield our fake module
        import pkgutil

        real_iter = pkgutil.iter_modules

        def patched_iter(path: Any = None, prefix: str = "") -> Any:
            yield from real_iter(path, prefix)
            # Inject our fake module info
            yield (None, "_test_fake", False)

        monkeypatch.setattr(pkgutil, "iter_modules", patched_iter)

        # Act
        result = discover_builtin_tools()

        # Assert
        assert "fake-tool" in result
        assert result["fake-tool"] is fake_fn
        assert callable(result["fake-tool"])

    def test_discovered_tool_metadata_matches(self, monkeypatch: Any) -> None:
        """Verify that discovered tool has correct metadata."""
        import importlib
        import types

        fake_mod = types.ModuleType("beddel.tools._test_meta")
        fake_mod.__package__ = "beddel.tools"

        @beddel_tool(name="meta-tool", description="Meta test", category="shell")
        def meta_fn() -> str:
            return "meta"

        fake_mod.meta_fn = meta_fn  # type: ignore[attr-defined]

        real_import = importlib.import_module

        def patched_import(name: str, package: str | None = None) -> types.ModuleType:
            if name == "beddel.tools._test_meta":
                return fake_mod
            return real_import(name, package)

        monkeypatch.setattr(importlib, "import_module", patched_import)

        import pkgutil

        real_iter = pkgutil.iter_modules

        def patched_iter(path: Any = None, prefix: str = "") -> Any:
            yield from real_iter(path, prefix)
            yield (None, "_test_meta", False)

        monkeypatch.setattr(pkgutil, "iter_modules", patched_iter)

        result = discover_builtin_tools()
        tool_fn: Callable[..., Any] = result["meta-tool"]
        meta: dict[str, str] = tool_fn._beddel_tool_meta  # type: ignore[attr-defined]
        assert meta["name"] == "meta-tool"
        assert meta["description"] == "Meta test"
        assert meta["category"] == "shell"
