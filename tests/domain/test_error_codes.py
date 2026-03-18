"""Tests for the centralized error code registry."""

from __future__ import annotations

import re

from beddel import error_codes
from beddel.error_codes import (
    ADAPT_RANGE,
    AGENT_ADAPTER_NOT_FOUND,
    AGENT_APPROVAL_NOT_IMPLEMENTED,
    AGENT_DELEGATION_FAILED,
    AGENT_EXECUTION_FAILED,
    AGENT_MISSING_ADAPTER,
    AGENT_MISSING_PROMPT,
    AGENT_NOT_CONFIGURED,
    AGENT_RANGE,
    AGENT_STREAM_INTERRUPTED,
    AGENT_TIMEOUT,
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
            "AGENT_RANGE": AGENT_RANGE,
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
            ("AGENT_RANGE", AGENT_RANGE),
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
        assert AGENT_RANGE == (700, 799)


class TestAgentCodes:
    """Tests for AGENT error code constants."""

    def test_agent_not_configured_value(self) -> None:
        """AGENT_NOT_CONFIGURED maps to BEDDEL-AGENT-700."""
        assert AGENT_NOT_CONFIGURED == "BEDDEL-AGENT-700"

    def test_agent_execution_failed_value(self) -> None:
        """AGENT_EXECUTION_FAILED maps to BEDDEL-AGENT-701."""
        assert AGENT_EXECUTION_FAILED == "BEDDEL-AGENT-701"

    def test_agent_timeout_value(self) -> None:
        """AGENT_TIMEOUT maps to BEDDEL-AGENT-702."""
        assert AGENT_TIMEOUT == "BEDDEL-AGENT-702"

    def test_agent_stream_interrupted_value(self) -> None:
        """AGENT_STREAM_INTERRUPTED maps to BEDDEL-AGENT-703."""
        assert AGENT_STREAM_INTERRUPTED == "BEDDEL-AGENT-703"

    def test_agent_missing_adapter_value(self) -> None:
        """AGENT_MISSING_ADAPTER maps to BEDDEL-AGENT-704."""
        assert AGENT_MISSING_ADAPTER == "BEDDEL-AGENT-704"

    def test_agent_missing_prompt_value(self) -> None:
        """AGENT_MISSING_PROMPT maps to BEDDEL-AGENT-705."""
        assert AGENT_MISSING_PROMPT == "BEDDEL-AGENT-705"

    def test_agent_adapter_not_found_value(self) -> None:
        """AGENT_ADAPTER_NOT_FOUND maps to BEDDEL-AGENT-706."""
        assert AGENT_ADAPTER_NOT_FOUND == "BEDDEL-AGENT-706"

    def test_agent_delegation_failed_value(self) -> None:
        """AGENT_DELEGATION_FAILED maps to BEDDEL-AGENT-707."""
        assert AGENT_DELEGATION_FAILED == "BEDDEL-AGENT-707"

    def test_agent_approval_not_implemented_value(self) -> None:
        """AGENT_APPROVAL_NOT_IMPLEMENTED maps to BEDDEL-AGENT-708."""
        assert AGENT_APPROVAL_NOT_IMPLEMENTED == "BEDDEL-AGENT-708"

    def test_all_agent_codes_in_all_codes(self) -> None:
        """All 9 AGENT codes are registered in ALL_CODES."""
        agent_keys = [
            "AGENT_NOT_CONFIGURED",
            "AGENT_EXECUTION_FAILED",
            "AGENT_TIMEOUT",
            "AGENT_STREAM_INTERRUPTED",
            "AGENT_MISSING_ADAPTER",
            "AGENT_MISSING_PROMPT",
            "AGENT_ADAPTER_NOT_FOUND",
            "AGENT_DELEGATION_FAILED",
            "AGENT_APPROVAL_NOT_IMPLEMENTED",
        ]
        for key in agent_keys:
            assert key in ALL_CODES, f"{key} missing from ALL_CODES"

    def test_agent_codes_count(self) -> None:
        """Exactly 9 AGENT codes exist in ALL_CODES."""
        agent_codes = {k: v for k, v in ALL_CODES.items() if k.startswith("AGENT_")}
        assert len(agent_codes) == 9


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
