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
    CB_CIRCUIT_OPEN,
    CB_FALLBACK_FAILED,
    CB_RANGE,
    CB_RECOVERY_PROBE_FAILED,
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
            "CB_RANGE": CB_RANGE,
        }
        for name, (lo, hi) in ranges.items():
            assert lo < hi, f"{name} lower bound >= upper bound"

    def test_ranges_do_not_overlap(self) -> None:
        # CB_RANGE shares numeric space with EXEC_RANGE but uses a different
        # prefix (CB vs EXEC), so it is excluded from the overlap check.
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


class TestToolUseLoopCodes:
    """Tool-use loop error codes (Story 4.0f) are registered correctly."""

    def test_tool_use_max_iterations_value(self) -> None:
        """PRIM_TOOL_USE_MAX_ITERATIONS maps to BEDDEL-PRIM-310."""
        assert ALL_CODES["PRIM_TOOL_USE_MAX_ITERATIONS"] == "BEDDEL-PRIM-310"

    def test_tool_use_not_found_value(self) -> None:
        """PRIM_TOOL_USE_NOT_FOUND maps to BEDDEL-PRIM-311."""
        assert ALL_CODES["PRIM_TOOL_USE_NOT_FOUND"] == "BEDDEL-PRIM-311"

    def test_tool_use_exec_failed_value(self) -> None:
        """PRIM_TOOL_USE_EXEC_FAILED maps to BEDDEL-PRIM-312."""
        assert ALL_CODES["PRIM_TOOL_USE_EXEC_FAILED"] == "BEDDEL-PRIM-312"

    def test_all_tool_use_codes_in_all_codes(self) -> None:
        """All 3 tool-use loop codes are registered in ALL_CODES."""
        keys = [
            "PRIM_TOOL_USE_MAX_ITERATIONS",
            "PRIM_TOOL_USE_NOT_FOUND",
            "PRIM_TOOL_USE_EXEC_FAILED",
        ]
        for key in keys:
            assert key in ALL_CODES, f"{key} missing from ALL_CODES"

    def test_tool_use_codes_match_prim_3xx_pattern(self) -> None:
        """All tool-use codes match BEDDEL-PRIM-3XX pattern."""
        import re

        pattern = re.compile(r"^BEDDEL-PRIM-3\d{2}$")
        codes = [
            ALL_CODES["PRIM_TOOL_USE_MAX_ITERATIONS"],
            ALL_CODES["PRIM_TOOL_USE_NOT_FOUND"],
            ALL_CODES["PRIM_TOOL_USE_EXEC_FAILED"],
        ]
        for code in codes:
            assert pattern.match(code), f"{code!r} does not match BEDDEL-PRIM-3XX"


class TestReflectionCodes:
    """Tests for reflection loop error codes (Story 4.1)."""

    def test_exec_reflection_no_generate_value(self) -> None:
        """EXEC_REFLECTION_NO_GENERATE maps to BEDDEL-EXEC-020."""
        assert ALL_CODES["EXEC_REFLECTION_NO_GENERATE"] == "BEDDEL-EXEC-020"

    def test_exec_reflection_no_evaluate_value(self) -> None:
        """EXEC_REFLECTION_NO_EVALUATE maps to BEDDEL-EXEC-021."""
        assert ALL_CODES["EXEC_REFLECTION_NO_EVALUATE"] == "BEDDEL-EXEC-021"

    def test_reflection_codes_in_all_codes(self) -> None:
        """Both reflection codes are registered in ALL_CODES."""
        assert "EXEC_REFLECTION_NO_GENERATE" in ALL_CODES
        assert "EXEC_REFLECTION_NO_EVALUATE" in ALL_CODES

    def test_reflection_codes_match_exec_pattern(self) -> None:
        """Both reflection codes match BEDDEL-EXEC-NNN pattern."""
        pattern = re.compile(r"^BEDDEL-EXEC-\d{3}$")
        assert pattern.match(ALL_CODES["EXEC_REFLECTION_NO_GENERATE"])
        assert pattern.match(ALL_CODES["EXEC_REFLECTION_NO_EVALUATE"])


class TestParallelCodes:
    """Tests for parallel execution error codes (Story 4.2a/4.2b)."""

    def test_exec_parallel_group_failed_value(self) -> None:
        """EXEC_PARALLEL_GROUP_FAILED maps to BEDDEL-EXEC-030."""
        assert ALL_CODES["EXEC_PARALLEL_GROUP_FAILED"] == "BEDDEL-EXEC-030"

    def test_parallel_code_in_all_codes(self) -> None:
        """Parallel error code is registered in ALL_CODES."""
        assert "EXEC_PARALLEL_GROUP_FAILED" in ALL_CODES

    def test_parallel_code_matches_exec_pattern(self) -> None:
        """Parallel code matches BEDDEL-EXEC-NNN pattern."""
        pattern = re.compile(r"^BEDDEL-EXEC-\d{3}$")
        assert pattern.match(ALL_CODES["EXEC_PARALLEL_GROUP_FAILED"])

    def test_exec_parallel_collect_failed_value(self) -> None:
        """EXEC_PARALLEL_COLLECT_FAILED maps to BEDDEL-EXEC-031."""
        assert ALL_CODES["EXEC_PARALLEL_COLLECT_FAILED"] == "BEDDEL-EXEC-031"

    def test_exec_parallel_collect_failed_in_all_codes(self) -> None:
        """Collect-all parallel error code is registered in ALL_CODES."""
        assert "EXEC_PARALLEL_COLLECT_FAILED" in ALL_CODES


class TestCircuitBreakerCodes:
    """Tests for circuit breaker error codes (Story 4.3)."""

    def test_cb_circuit_open_value(self) -> None:
        """CB_CIRCUIT_OPEN maps to BEDDEL-CB-500."""
        assert CB_CIRCUIT_OPEN == "BEDDEL-CB-500"

    def test_cb_fallback_failed_value(self) -> None:
        """CB_FALLBACK_FAILED maps to BEDDEL-CB-501."""
        assert CB_FALLBACK_FAILED == "BEDDEL-CB-501"

    def test_cb_recovery_probe_failed_value(self) -> None:
        """CB_RECOVERY_PROBE_FAILED maps to BEDDEL-CB-502."""
        assert CB_RECOVERY_PROBE_FAILED == "BEDDEL-CB-502"

    def test_cb_range_value(self) -> None:
        """CB_RANGE is (500, 549)."""
        assert CB_RANGE == (500, 549)

    def test_cb_circuit_open_in_all_codes(self) -> None:
        """CB_CIRCUIT_OPEN is registered in ALL_CODES."""
        assert "CB_CIRCUIT_OPEN" in ALL_CODES

    def test_cb_fallback_failed_in_all_codes(self) -> None:
        """CB_FALLBACK_FAILED is registered in ALL_CODES."""
        assert "CB_FALLBACK_FAILED" in ALL_CODES

    def test_cb_recovery_probe_failed_in_all_codes(self) -> None:
        """CB_RECOVERY_PROBE_FAILED is registered in ALL_CODES."""
        assert "CB_RECOVERY_PROBE_FAILED" in ALL_CODES

    def test_cb_codes_match_pattern(self) -> None:
        """All CB codes match BEDDEL-CB-NNN pattern."""
        pattern = re.compile(r"^BEDDEL-CB-\d{3}$")
        assert pattern.match(ALL_CODES["CB_CIRCUIT_OPEN"])
        assert pattern.match(ALL_CODES["CB_FALLBACK_FAILED"])
        assert pattern.match(ALL_CODES["CB_RECOVERY_PROBE_FAILED"])
