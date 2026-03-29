"""Tests for InMemoryBudgetEnforcer adapter."""

from __future__ import annotations

from beddel.adapters.budget_enforcer import InMemoryBudgetEnforcer
from beddel.domain.models import BudgetStatus


class TestInMemoryBudgetEnforcerWithinBudget:
    """Track usage below threshold, verify WITHIN_BUDGET and correct remaining."""

    def test_within_budget(self) -> None:
        # Arrange
        enforcer = InMemoryBudgetEnforcer(max_cost_usd=10.0)

        # Act
        enforcer.track_usage("step-1", {"total_cost": 2.0})

        # Assert
        assert enforcer.check_budget() == BudgetStatus.WITHIN_BUDGET
        assert enforcer.get_remaining() == 8.0


class TestInMemoryBudgetEnforcerDegraded:
    """Track usage past degradation threshold, verify DEGRADED."""

    def test_degraded_at_threshold(self) -> None:
        # Arrange — default threshold is 0.8, so 8.0 of 10.0 triggers DEGRADED
        enforcer = InMemoryBudgetEnforcer(max_cost_usd=10.0)

        # Act
        enforcer.track_usage("step-1", {"total_cost": 8.0})

        # Assert
        assert enforcer.check_budget() == BudgetStatus.DEGRADED


class TestInMemoryBudgetEnforcerExceeded:
    """Track usage past max_cost_usd, verify EXCEEDED."""

    def test_exceeded_at_max(self) -> None:
        # Arrange
        enforcer = InMemoryBudgetEnforcer(max_cost_usd=5.0)

        # Act
        enforcer.track_usage("step-1", {"total_cost": 5.0})

        # Assert
        assert enforcer.check_budget() == BudgetStatus.EXCEEDED

    def test_exceeded_over_max(self) -> None:
        # Arrange
        enforcer = InMemoryBudgetEnforcer(max_cost_usd=5.0)

        # Act
        enforcer.track_usage("step-1", {"total_cost": 7.0})

        # Assert
        assert enforcer.check_budget() == BudgetStatus.EXCEEDED


class TestInMemoryBudgetEnforcerGetRemaining:
    """Verify get_remaining() returns 0.0 when exceeded, correct delta otherwise."""

    def test_remaining_zero_when_exceeded(self) -> None:
        # Arrange
        enforcer = InMemoryBudgetEnforcer(max_cost_usd=5.0)
        enforcer.track_usage("step-1", {"total_cost": 10.0})

        # Act & Assert
        assert enforcer.get_remaining() == 0.0

    def test_remaining_correct_delta(self) -> None:
        # Arrange
        enforcer = InMemoryBudgetEnforcer(max_cost_usd=10.0)
        enforcer.track_usage("step-1", {"total_cost": 3.5})

        # Act & Assert
        assert enforcer.get_remaining() == 6.5


class TestInMemoryBudgetEnforcerMissingCost:
    """Track usage with no total_cost key, verify graceful fallback to 0.0."""

    def test_missing_total_cost_defaults_to_zero(self) -> None:
        # Arrange
        enforcer = InMemoryBudgetEnforcer(max_cost_usd=10.0)

        # Act
        enforcer.track_usage("step-1", {"prompt_tokens": 100})

        # Assert
        assert enforcer.cumulative_cost == 0.0
        assert enforcer.check_budget() == BudgetStatus.WITHIN_BUDGET
        assert enforcer.get_remaining() == 10.0

    def test_empty_usage_dict(self) -> None:
        # Arrange
        enforcer = InMemoryBudgetEnforcer(max_cost_usd=10.0)

        # Act
        enforcer.track_usage("step-1", {})

        # Assert
        assert enforcer.cumulative_cost == 0.0


class TestInMemoryBudgetEnforcerStepTracking:
    """Track multiple steps, verify per-step costs stored correctly."""

    def test_multiple_steps_tracked(self) -> None:
        # Arrange
        enforcer = InMemoryBudgetEnforcer(max_cost_usd=20.0)

        # Act
        enforcer.track_usage("step-1", {"total_cost": 2.0})
        enforcer.track_usage("step-2", {"total_cost": 3.5})
        enforcer.track_usage("step-3", {"total_cost": 1.0})

        # Assert
        assert enforcer.step_costs == {
            "step-1": 2.0,
            "step-2": 3.5,
            "step-3": 1.0,
        }
        assert enforcer.cumulative_cost == 6.5
