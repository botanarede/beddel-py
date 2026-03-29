"""In-memory budget enforcer adapter for per-workflow cost tracking.

Implements :class:`~beddel.domain.ports.IBudgetEnforcer` with simple
in-memory cumulative cost tracking.  Suitable for single-workflow
executions where persistence is not required.

Uses structural subtyping (Protocol conformance, no explicit inheritance)
— consistent with :class:`~beddel.adapters.tier_router.StaticTierRouter`
and :class:`~beddel.adapters.circuit_breaker.InMemoryCircuitBreaker`.
"""

from __future__ import annotations

from typing import Any

from beddel.domain.models import BudgetStatus

__all__ = ["InMemoryBudgetEnforcer"]


class InMemoryBudgetEnforcer:
    """In-memory per-workflow budget enforcer.

    Satisfies the :class:`~beddel.domain.ports.IBudgetEnforcer` protocol
    via structural subtyping.

    Tracks cumulative cost from LiteLLM ``usage`` dicts and reports the
    current budget state.  When cumulative cost reaches
    ``degradation_threshold × max_cost_usd``, the status transitions to
    ``DEGRADED``.  When it reaches ``max_cost_usd``, the status becomes
    ``EXCEEDED``.

    Args:
        max_cost_usd: Hard budget limit in USD.
        degradation_threshold: Fraction of ``max_cost_usd`` at which to
            trigger model degradation (0.0–1.0).  Defaults to ``0.8``.
        degradation_model: Model identifier to downgrade to when the
            degradation threshold is reached.  Defaults to ``"gpt-4o-mini"``.

    Example::

        enforcer = InMemoryBudgetEnforcer(max_cost_usd=5.0)
        enforcer.track_usage("step-1", {"total_cost": 1.50})
        enforcer.check_budget()   # BudgetStatus.WITHIN_BUDGET
        enforcer.get_remaining()  # 3.5
    """

    __slots__ = (
        "_cumulative_cost",
        "_degradation_model",
        "_degradation_threshold",
        "_degraded",
        "_max_cost_usd",
        "_step_costs",
    )

    def __init__(
        self,
        max_cost_usd: float,
        degradation_threshold: float = 0.8,
        degradation_model: str = "gpt-4o-mini",
    ) -> None:
        self._max_cost_usd = max_cost_usd
        self._degradation_threshold = degradation_threshold
        self._degradation_model = degradation_model
        self._cumulative_cost: float = 0.0
        self._step_costs: dict[str, float] = {}
        self._degraded: bool = False

    # -- Public properties (read-only) ----------------------------------------

    @property
    def degradation_model(self) -> str:
        """Model identifier used when budget is degraded."""
        return self._degradation_model

    @property
    def max_cost_usd(self) -> float:
        """Hard budget limit in USD."""
        return self._max_cost_usd

    @property
    def degradation_threshold(self) -> float:
        """Fraction of ``max_cost_usd`` that triggers degradation."""
        return self._degradation_threshold

    @property
    def cumulative_cost(self) -> float:
        """Total cost accumulated so far."""
        return self._cumulative_cost

    @property
    def step_costs(self) -> dict[str, float]:
        """Per-step cost breakdown."""
        return dict(self._step_costs)

    # -- IBudgetEnforcer protocol methods -------------------------------------

    def track_usage(self, step_id: str, usage: dict[str, Any]) -> None:
        """Record token/cost usage for a completed step.

        Extracts ``total_cost`` from the *usage* dict (falls back to
        ``0.0`` if the key is missing) and adds it to the cumulative
        total and per-step tracking.

        Args:
            step_id: Identifier of the step that produced the usage data.
            usage: Usage dict from the LLM provider response.
        """
        cost = float(usage.get("total_cost", 0.0))
        self._cumulative_cost += cost
        self._step_costs[step_id] = cost

    def check_budget(self) -> BudgetStatus:
        """Return the current budget state.

        Returns:
            ``EXCEEDED`` if cumulative cost ≥ ``max_cost_usd``;
            ``DEGRADED`` if cumulative cost ≥ ``degradation_threshold × max_cost_usd``;
            ``WITHIN_BUDGET`` otherwise.
        """
        if self._cumulative_cost >= self._max_cost_usd:
            return BudgetStatus.EXCEEDED
        if self._cumulative_cost >= self._degradation_threshold * self._max_cost_usd:
            return BudgetStatus.DEGRADED
        return BudgetStatus.WITHIN_BUDGET

    def get_remaining(self) -> float:
        """Return the remaining budget in USD.

        Returns:
            Non-negative float representing the remaining budget.
            Returns ``0.0`` when the budget is fully consumed.
        """
        return max(0.0, self._max_cost_usd - self._cumulative_cost)
