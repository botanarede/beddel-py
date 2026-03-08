"""Tests for the centralized error code registry."""

from __future__ import annotations

import re

from beddel import error_codes
from beddel.error_codes import (
    ADAPT_RANGE,
    ALL_CODES,
    EXEC_RANGE,
    GUARD_RANGE,
    PARSE_RANGE,
    PRIM_RANGE,
    RESOLVE_RANGE,
)

# Valid code pattern: BEDDEL-{PREFIX}-{NNN}
_CODE_PATTERN = re.compile(r"^BEDDEL-[A-Z]+-\d{3}$")


class TestErrorCodeFormat:
    """All codes follow the BEDDEL-{PREFIX}-{NNN} pattern."""

    def test_all_codes_match_pattern(self) -> None:
        for name, code in ALL_CODES.items():
            assert _CODE_PATTERN.match(code), f"{name} = {code!r} does not match BEDDEL-PREFIX-NNN"


class TestNoDuplicates:
    """No two constants share the same code string."""

    def test_no_duplicate_code_values(self) -> None:
        seen: dict[str, str] = {}
        for name, code in ALL_CODES.items():
            assert code not in seen, f"Duplicate code {code!r}: {seen[code]} and {name}"
            seen[code] = name


class TestRanges:
    """Range boundary constants are correct and non-overlapping."""

    def test_range_boundaries(self) -> None:
        ranges = {
            "PARSE_RANGE": PARSE_RANGE,
            "GUARD_RANGE": GUARD_RANGE,
            "PRIM_RANGE": PRIM_RANGE,
            "ADAPT_RANGE": ADAPT_RANGE,
            "EXEC_RANGE": EXEC_RANGE,
            "RESOLVE_RANGE": RESOLVE_RANGE,
        }
        for name, (lo, hi) in ranges.items():
            assert lo < hi, f"{name} lower bound >= upper bound"

    def test_ranges_do_not_overlap(self) -> None:
        ranges = [
            ("PARSE_RANGE", PARSE_RANGE),
            ("GUARD_RANGE", GUARD_RANGE),
            ("PRIM_RANGE", PRIM_RANGE),
            ("ADAPT_RANGE", ADAPT_RANGE),
            ("EXEC_RANGE", EXEC_RANGE),
            ("RESOLVE_RANGE", RESOLVE_RANGE),
        ]
        for i, (name_a, (lo_a, hi_a)) in enumerate(ranges):
            for name_b, (lo_b, hi_b) in ranges[i + 1 :]:
                assert hi_a < lo_b or hi_b < lo_a, (
                    f"{name_a} ({lo_a}-{hi_a}) overlaps {name_b} ({lo_b}-{hi_b})"
                )

    def test_expected_range_values(self) -> None:
        assert PARSE_RANGE == (100, 199)
        assert GUARD_RANGE == (200, 299)
        assert PRIM_RANGE == (300, 399)
        assert ADAPT_RANGE == (400, 499)
        assert EXEC_RANGE == (500, 599)
        assert RESOLVE_RANGE == (600, 699)


class TestAllCodesCompleteness:
    """ALL_CODES dict contains every constant defined in the module."""

    def test_all_codes_matches_module_constants(self) -> None:
        # Collect all SCREAMING_SNAKE_CASE string constants from the module
        module_codes: dict[str, str] = {}
        for attr in dir(error_codes):
            if attr.startswith("_") or not attr.isupper():
                continue
            val = getattr(error_codes, attr)
            if isinstance(val, str) and val.startswith("BEDDEL-"):
                module_codes[attr] = val

        assert module_codes == ALL_CODES, (
            f"ALL_CODES mismatch.\n"
            f"  Missing from ALL_CODES: {set(module_codes) - set(ALL_CODES)}\n"
            f"  Extra in ALL_CODES: {set(ALL_CODES) - set(module_codes)}"
        )


class TestModuleExport:
    """error_codes is accessible from the beddel package."""

    def test_error_codes_in_beddel_all(self) -> None:
        import beddel

        assert "error_codes" in beddel.__all__

    def test_import_error_codes_from_beddel(self) -> None:
        from beddel import error_codes as ec

        assert hasattr(ec, "ALL_CODES")


class TestTracingFailureCode:
    """TRACING_FAILURE code is registered correctly."""

    def test_tracing_failure_in_all_codes(self) -> None:
        """TRACING_FAILURE must be registered in ALL_CODES."""
        assert "TRACING_FAILURE" in ALL_CODES

    def test_tracing_failure_code_value(self) -> None:
        """TRACING_FAILURE maps to BEDDEL-ADAPT-010."""
        assert ALL_CODES["TRACING_FAILURE"] == "BEDDEL-ADAPT-010"


class TestPrimInvalidMessageCode:
    """PRIM_INVALID_MESSAGE code is registered correctly."""

    def test_prim_invalid_message_in_all_codes(self) -> None:
        """PRIM_INVALID_MESSAGE must be registered in ALL_CODES."""
        assert "PRIM_INVALID_MESSAGE" in ALL_CODES

    def test_prim_invalid_message_code_value(self) -> None:
        """PRIM_INVALID_MESSAGE maps to BEDDEL-PRIM-006."""
        assert ALL_CODES["PRIM_INVALID_MESSAGE"] == "BEDDEL-PRIM-006"
