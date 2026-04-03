"""Unit tests for beddel.tools — @beddel_tool decorator and discover_builtin_tools()."""

from __future__ import annotations

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

    def test_returns_empty_after_kit_extraction(self) -> None:
        """After kit extraction, no builtin tool submodules remain."""
        result = discover_builtin_tools()
        assert result == {}
