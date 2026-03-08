"""Unit tests for beddel.primitives.utils module."""

from __future__ import annotations

import pytest

from beddel.domain.errors import PrimitiveError
from beddel.primitives.utils import validate_message


class TestValidateMessage:
    """Tests for validate_message() utility function."""

    def test_rejects_empty_dict(self) -> None:
        """Empty dict is missing both required keys."""
        with pytest.raises(PrimitiveError) as exc_info:
            validate_message({})

        assert exc_info.value.code == "BEDDEL-PRIM-005"

    def test_rejects_missing_content(self) -> None:
        """Dict with only 'role' is missing 'content'."""
        with pytest.raises(PrimitiveError) as exc_info:
            validate_message({"role": "user"})

        assert exc_info.value.code == "BEDDEL-PRIM-005"
        assert "content" in exc_info.value.message

    def test_rejects_missing_role(self) -> None:
        """Dict with only 'content' is missing 'role'."""
        with pytest.raises(PrimitiveError) as exc_info:
            validate_message({"content": "hi"})

        assert exc_info.value.code == "BEDDEL-PRIM-005"
        assert "role" in exc_info.value.message

    def test_accepts_valid_message(self) -> None:
        """Valid message with both required keys does not raise."""
        validate_message({"role": "user", "content": "hi"})

    def test_accepts_message_with_extra_keys(self) -> None:
        """Extra keys beyond role/content are allowed."""
        validate_message({"role": "user", "content": "hi", "name": "bot"})

    def test_error_details_contain_missing_keys(self) -> None:
        """Error details include which keys are missing."""
        with pytest.raises(PrimitiveError) as exc_info:
            validate_message({})

        assert "missing_keys" in exc_info.value.details
        assert sorted(exc_info.value.details["missing_keys"]) == ["content", "role"]


class TestErrorCodeRegistry:
    """Verify error code registry integrity (Story 3.5)."""

    def test_no_duplicate_error_codes(self) -> None:
        """ALL_CODES values must be unique — no two names share a code string."""
        from beddel.error_codes import ALL_CODES

        values = list(ALL_CODES.values())
        assert len(values) == len(set(values)), (
            f"Duplicate codes found: {[v for v in values if values.count(v) > 1]}"
        )

    def test_tracing_failure_in_all_codes(self) -> None:
        """TRACING_FAILURE must be registered in ALL_CODES."""
        from beddel.error_codes import ALL_CODES

        assert "TRACING_FAILURE" in ALL_CODES

    def test_tracing_failure_code_value(self) -> None:
        """TRACING_FAILURE maps to BEDDEL-ADAPT-010."""
        from beddel.error_codes import ALL_CODES

        assert ALL_CODES["TRACING_FAILURE"] == "BEDDEL-ADAPT-010"
