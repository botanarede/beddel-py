"""Unit tests for approval gate domain models (Story 6.1, Task 6.1).

Tests: RiskLevel, ApprovalStatus, ApprovalResult, ApprovalPolicy, RiskMatrix.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from typing import Any

import pytest

from beddel.domain.models import (
    ApprovalPolicy,
    ApprovalResult,
    ApprovalStatus,
    RiskLevel,
    RiskMatrix,
)

# ---------------------------------------------------------------------------
# RiskLevel enum
# ---------------------------------------------------------------------------


class TestRiskLevel:
    """RiskLevel enum has the expected members and values."""

    def test_low_value(self) -> None:
        assert RiskLevel.LOW == "low"

    def test_medium_value(self) -> None:
        assert RiskLevel.MEDIUM == "medium"

    def test_high_value(self) -> None:
        assert RiskLevel.HIGH == "high"

    def test_critical_value(self) -> None:
        assert RiskLevel.CRITICAL == "critical"

    def test_member_count(self) -> None:
        assert len(RiskLevel) == 4

    def test_is_str_enum(self) -> None:
        assert isinstance(RiskLevel.LOW, str)


# ---------------------------------------------------------------------------
# ApprovalStatus enum
# ---------------------------------------------------------------------------


class TestApprovalStatus:
    """ApprovalStatus enum has the expected members and values."""

    def test_pending_value(self) -> None:
        assert ApprovalStatus.PENDING == "pending"

    def test_approved_value(self) -> None:
        assert ApprovalStatus.APPROVED == "approved"

    def test_denied_value(self) -> None:
        assert ApprovalStatus.DENIED == "denied"

    def test_timeout_value(self) -> None:
        assert ApprovalStatus.TIMEOUT == "timeout"

    def test_escalated_value(self) -> None:
        assert ApprovalStatus.ESCALATED == "escalated"

    def test_member_count(self) -> None:
        assert len(ApprovalStatus) == 5

    def test_is_str_enum(self) -> None:
        assert isinstance(ApprovalStatus.PENDING, str)


# ---------------------------------------------------------------------------
# ApprovalResult frozen dataclass
# ---------------------------------------------------------------------------


class TestApprovalResult:
    """ApprovalResult is a frozen dataclass with correct defaults."""

    def test_creation_with_required_fields(self) -> None:
        result = ApprovalResult(request_id="req-1", status=ApprovalStatus.APPROVED)
        assert result.request_id == "req-1"
        assert result.status == ApprovalStatus.APPROVED

    def test_defaults(self) -> None:
        result = ApprovalResult(request_id="req-1", status=ApprovalStatus.PENDING)
        assert result.approver is None
        assert result.timestamp == 0.0
        assert result.metadata == {}

    def test_custom_values(self) -> None:
        meta: dict[str, Any] = {"action": "delete_db"}
        result = ApprovalResult(
            request_id="req-2",
            status=ApprovalStatus.DENIED,
            approver="alice",
            timestamp=1234567890.0,
            metadata=meta,
        )
        assert result.approver == "alice"
        assert result.timestamp == 1234567890.0
        assert result.metadata == {"action": "delete_db"}

    def test_immutability_request_id(self) -> None:
        result = ApprovalResult(request_id="req-1", status=ApprovalStatus.APPROVED)
        with pytest.raises(FrozenInstanceError):
            result.request_id = "changed"  # type: ignore[misc]

    def test_immutability_status(self) -> None:
        result = ApprovalResult(request_id="req-1", status=ApprovalStatus.APPROVED)
        with pytest.raises(FrozenInstanceError):
            result.status = ApprovalStatus.DENIED  # type: ignore[misc]

    def test_immutability_approver(self) -> None:
        result = ApprovalResult(request_id="req-1", status=ApprovalStatus.APPROVED)
        with pytest.raises(FrozenInstanceError):
            result.approver = "bob"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# ApprovalPolicy defaults and custom values
# ---------------------------------------------------------------------------


class TestApprovalPolicy:
    """ApprovalPolicy BaseModel has correct defaults and accepts custom values."""

    def test_defaults(self) -> None:
        policy = ApprovalPolicy()
        assert policy.auto_approve_levels == [RiskLevel.LOW]
        assert policy.timeout_seconds == 300.0
        assert policy.escalation_policy == "auto-deny"
        assert policy.risk_matrix == {}

    def test_custom_auto_approve_levels(self) -> None:
        policy = ApprovalPolicy(
            auto_approve_levels=[RiskLevel.LOW, RiskLevel.MEDIUM],
        )
        assert RiskLevel.LOW in policy.auto_approve_levels
        assert RiskLevel.MEDIUM in policy.auto_approve_levels

    def test_custom_timeout(self) -> None:
        policy = ApprovalPolicy(timeout_seconds=60.0)
        assert policy.timeout_seconds == 60.0

    def test_custom_escalation_policy(self) -> None:
        policy = ApprovalPolicy(escalation_policy="auto-approve")
        assert policy.escalation_policy == "auto-approve"

    def test_custom_risk_matrix(self) -> None:
        policy = ApprovalPolicy(
            risk_matrix={"deploy": RiskLevel.CRITICAL},
        )
        assert policy.risk_matrix["deploy"] == RiskLevel.CRITICAL


# ---------------------------------------------------------------------------
# RiskMatrix.classify()
# ---------------------------------------------------------------------------


class TestRiskMatrix:
    """RiskMatrix classifies actions using prefix matching and overrides."""

    # --- LOW prefixes ---

    def test_read_prefix_is_low(self) -> None:
        matrix = RiskMatrix()
        assert matrix.classify("read_file") == RiskLevel.LOW

    def test_get_prefix_is_low(self) -> None:
        matrix = RiskMatrix()
        assert matrix.classify("get_status") == RiskLevel.LOW

    def test_list_prefix_is_low(self) -> None:
        matrix = RiskMatrix()
        assert matrix.classify("list_users") == RiskLevel.LOW

    def test_describe_prefix_is_low(self) -> None:
        matrix = RiskMatrix()
        assert matrix.classify("describe_instance") == RiskLevel.LOW

    # --- MEDIUM prefixes ---

    def test_write_prefix_is_medium(self) -> None:
        matrix = RiskMatrix()
        assert matrix.classify("write_config") == RiskLevel.MEDIUM

    def test_update_prefix_is_medium(self) -> None:
        matrix = RiskMatrix()
        assert matrix.classify("update_record") == RiskLevel.MEDIUM

    def test_create_prefix_is_medium(self) -> None:
        matrix = RiskMatrix()
        assert matrix.classify("create_user") == RiskLevel.MEDIUM

    def test_put_prefix_is_medium(self) -> None:
        matrix = RiskMatrix()
        assert matrix.classify("put_item") == RiskLevel.MEDIUM

    # --- HIGH prefixes ---

    def test_delete_prefix_is_high(self) -> None:
        matrix = RiskMatrix()
        assert matrix.classify("delete_database") == RiskLevel.HIGH

    def test_remove_prefix_is_high(self) -> None:
        matrix = RiskMatrix()
        assert matrix.classify("remove_user") == RiskLevel.HIGH

    def test_drop_prefix_is_high(self) -> None:
        matrix = RiskMatrix()
        assert matrix.classify("drop_table") == RiskLevel.HIGH

    def test_destroy_prefix_is_high(self) -> None:
        matrix = RiskMatrix()
        assert matrix.classify("destroy_cluster") == RiskLevel.HIGH

    # --- Fallback ---

    def test_unknown_action_falls_back_to_medium(self) -> None:
        matrix = RiskMatrix()
        assert matrix.classify("unknown_action") == RiskLevel.MEDIUM

    def test_empty_string_falls_back_to_medium(self) -> None:
        matrix = RiskMatrix()
        assert matrix.classify("") == RiskLevel.MEDIUM

    # --- Case insensitivity ---

    def test_case_insensitive_prefix_matching(self) -> None:
        matrix = RiskMatrix()
        assert matrix.classify("READ_FILE") == RiskLevel.LOW
        assert matrix.classify("Delete_DB") == RiskLevel.HIGH

    # --- Custom overrides ---

    def test_override_takes_precedence(self) -> None:
        matrix = RiskMatrix(overrides={"read_secrets": RiskLevel.CRITICAL})
        assert matrix.classify("read_secrets") == RiskLevel.CRITICAL

    def test_override_exact_match_only(self) -> None:
        """Override applies to exact action name, not prefix."""
        matrix = RiskMatrix(overrides={"deploy": RiskLevel.CRITICAL})
        assert matrix.classify("deploy") == RiskLevel.CRITICAL
        # "deploy_app" is NOT in overrides, falls back to prefix matching → MEDIUM
        assert matrix.classify("deploy_app") == RiskLevel.MEDIUM

    def test_no_overrides_by_default(self) -> None:
        matrix = RiskMatrix()
        assert matrix.classify("read_file") == RiskLevel.LOW
