"""Unit tests for _parse_tool_flags helper (Story 4.0a, Task 2)."""

from __future__ import annotations

import click
import pytest

from beddel.cli.commands import _parse_tool_flags


class TestParseToolFlags:
    """Tests for the _parse_tool_flags helper function."""

    def test_parse_valid_tool_flag(self) -> None:
        """Valid 'name=module:function' resolves to a callable dict entry."""
        result = _parse_tool_flags(("my_tool=json:dumps",))
        assert "my_tool" in result
        import json

        assert result["my_tool"] is json.dumps

    def test_parse_multiple_valid_flags(self) -> None:
        """Multiple valid flags all resolve correctly."""
        result = _parse_tool_flags(("a=json:dumps", "b=json:loads"))
        assert len(result) == 2
        import json

        assert result["a"] is json.dumps
        assert result["b"] is json.loads

    def test_parse_empty_tuple(self) -> None:
        """Empty tuple returns empty dict."""
        result = _parse_tool_flags(())
        assert result == {}

    def test_parse_invalid_format_missing_equals(self) -> None:
        """Missing '=' raises click.BadParameter."""
        with pytest.raises(click.BadParameter, match="Expected format"):
            _parse_tool_flags(("no_equals_here",))

    def test_parse_invalid_format_missing_colon(self) -> None:
        """Has '=' but missing ':' raises click.BadParameter."""
        with pytest.raises(click.BadParameter, match="Expected format"):
            _parse_tool_flags(("name=moduleonly",))

    def test_parse_import_error(self) -> None:
        """Non-existent module raises click.BadParameter."""
        with pytest.raises(click.BadParameter, match="Cannot import tool"):
            _parse_tool_flags(("bad=nonexistent_module_xyz:func",))

    def test_parse_attribute_error(self) -> None:
        """Existing module but missing attribute raises click.BadParameter."""
        with pytest.raises(click.BadParameter, match="Cannot import tool"):
            _parse_tool_flags(("bad=json:nonexistent_function_xyz",))

    def test_parse_non_callable(self) -> None:
        """Module attribute that is not callable raises click.BadParameter."""
        # json.decoder is a module attribute but not callable in the expected sense;
        # use a known non-callable constant instead.
        with pytest.raises(click.BadParameter, match="not callable"):
            _parse_tool_flags(("bad=json:__name__",))
