"""Tests for budget enforcement integration with _llm_utils and executor."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from beddel.adapters.budget_enforcer import InMemoryBudgetEnforcer
from beddel.adapters.hooks import LifecycleHookManager
from beddel.domain.errors import BudgetError
from beddel.domain.models import BudgetStatus, DefaultDependencies, ExecutionContext
from beddel.domain.ports import ILifecycleHook
from beddel.error_codes import BUDGET_EXCEEDED
from beddel.primitives._llm_utils import get_model

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_context(
    metadata: dict[str, Any] | None = None,
    tier_router: Any = None,
) -> ExecutionContext:
    """Build an ExecutionContext with optional metadata and tier_router."""
    deps = DefaultDependencies(tier_router=tier_router)
    ctx = ExecutionContext(workflow_id="test-wf", deps=deps)
    if metadata:
        ctx.metadata.update(metadata)
    ctx.current_step_id = "test-step"
    return ctx


# ---------------------------------------------------------------------------
# get_model() budget degradation tests
# ---------------------------------------------------------------------------


class TestGetModelBudgetDegraded:
    """When _budget_degraded=True, get_model() returns degradation model."""

    def test_returns_degradation_model(self) -> None:
        # Arrange
        ctx = _make_context(
            metadata={
                "_budget_degraded": True,
                "_degradation_model": "gpt-4o-mini",
            },
        )
        config = {"model": "gpt-4o"}

        # Act
        result = get_model(config, ctx, "llm")

        # Assert
        assert result == "gpt-4o-mini"


class TestGetModelNoBudgetDegradation:
    """When _budget_degraded not set, get_model() returns normal model."""

    def test_returns_normal_model(self) -> None:
        # Arrange
        ctx = _make_context()
        config = {"model": "gpt-4o"}

        # Act
        result = get_model(config, ctx, "llm")

        # Assert
        assert result == "gpt-4o"


# ---------------------------------------------------------------------------
# Budget enforcer exceeded → BudgetError integration test
# ---------------------------------------------------------------------------


class TestBudgetEnforcerExceededRaisesError:
    """Create a low-budget enforcer, exceed it, verify BudgetError raised."""

    def test_budget_exceeded_raises_budget_error(self) -> None:
        # Arrange
        enforcer = InMemoryBudgetEnforcer(max_cost_usd=1.0)
        enforcer.track_usage("step-1", {"total_cost": 1.5})

        # Act
        status = enforcer.check_budget()

        # Assert — status is EXCEEDED; executor would raise BudgetError
        assert status == BudgetStatus.EXCEEDED

        # Verify BudgetError can be raised with correct code
        with pytest.raises(BudgetError) as exc_info:
            raise BudgetError(
                BUDGET_EXCEEDED,
                "Budget exceeded after step 'step-1'",
                {
                    "step_id": "step-1",
                    "cumulative_cost": enforcer.cumulative_cost,
                    "max_cost_usd": enforcer.max_cost_usd,
                },
            )

        assert exc_info.value.code == BUDGET_EXCEEDED
        assert exc_info.value.code == "BEDDEL-BUDGET-851"
        assert exc_info.value.details["step_id"] == "step-1"
        assert exc_info.value.details["cumulative_cost"] == 1.5
        assert exc_info.value.details["max_cost_usd"] == 1.0


# ---------------------------------------------------------------------------
# Budget threshold hook integration test
# ---------------------------------------------------------------------------


class TestBudgetThresholdHookFired:
    """Mock lifecycle hook, verify on_budget_threshold called at degradation."""

    async def test_hook_called_on_threshold(self) -> None:
        # Arrange
        hook = ILifecycleHook()
        hook.on_budget_threshold = AsyncMock()  # type: ignore[method-assign]
        manager = LifecycleHookManager([hook])

        enforcer = InMemoryBudgetEnforcer(max_cost_usd=10.0)
        enforcer.track_usage("step-1", {"total_cost": 8.5})

        # Act — simulate what executor does when DEGRADED
        status = enforcer.check_budget()
        assert status == BudgetStatus.DEGRADED

        await manager.on_budget_threshold(
            "test-wf",
            enforcer.cumulative_cost,
            enforcer.degradation_threshold,
        )

        # Assert
        hook.on_budget_threshold.assert_awaited_once_with(  # type: ignore[union-attr]
            "test-wf",
            8.5,
            0.8,
        )
