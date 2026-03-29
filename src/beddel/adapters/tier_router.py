"""Static tier router adapter for model tier resolution.

Implements :class:`~beddel.domain.ports.ITierRouter` with a simple
dict-based lookup from logical tier names to concrete model identifiers.

Uses structural subtyping (Protocol conformance, no explicit inheritance)
— consistent with :class:`~beddel.adapters.circuit_breaker.InMemoryCircuitBreaker`
and :class:`~beddel.domain.executor.SequentialStrategy`.
"""

from __future__ import annotations

from beddel.domain.errors import PrimitiveError
from beddel.error_codes import TIER_UNKNOWN

__all__ = ["StaticTierRouter"]

DEFAULT_TIERS: dict[str, str] = {
    "fast": "gpt-4o-mini",
    "balanced": "gpt-4o",
    "powerful": "claude-opus-4",
}
"""Default tier-to-model mapping used when no custom tiers are provided."""


class StaticTierRouter:
    """Static dict-based tier router.

    Satisfies the :class:`~beddel.domain.ports.ITierRouter` protocol
    via structural subtyping.

    Maps logical tier names (e.g. ``"fast"``, ``"balanced"``,
    ``"powerful"``) to concrete model identifiers using a simple dict
    lookup.  The ``prompt_complexity`` parameter is accepted but ignored
    — reserved for future adaptive routing implementations.

    Args:
        tiers: Optional tier-to-model mapping.  Defaults to
            :data:`DEFAULT_TIERS` when ``None``.

    Example::

        router = StaticTierRouter()
        model = router.route("fast")  # "gpt-4o-mini"

        custom = StaticTierRouter(tiers={"fast": "llama-3"})
        model = custom.route("fast")  # "llama-3"
    """

    DEFAULT_TIERS: dict[str, str] = DEFAULT_TIERS

    def __init__(self, tiers: dict[str, str] | None = None) -> None:
        self._tiers: dict[str, str] = (
            dict(tiers) if tiers is not None else dict(self.DEFAULT_TIERS)
        )

    def route(self, tier: str, prompt_complexity: float | None = None) -> str:
        """Resolve a tier name to a concrete model identifier.

        Args:
            tier: Logical tier name (e.g. ``"fast"``, ``"balanced"``,
                ``"powerful"``).
            prompt_complexity: Optional complexity score for adaptive
                routing.  Ignored by this static implementation; reserved
                for future bandit-based routers.

        Returns:
            A concrete model identifier string (e.g. ``"gpt-4o-mini"``).

        Raises:
            PrimitiveError: ``BEDDEL-PRIM-320`` when *tier* is not found
                in the tier-to-model mapping.
        """
        if tier in self._tiers:
            return self._tiers[tier]
        raise PrimitiveError(
            TIER_UNKNOWN,
            f"Unknown model tier: '{tier}'",
            {"tier": tier, "available_tiers": list(self._tiers.keys())},
        )
