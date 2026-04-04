"""Decide primitive — structured decision capture for Beddel workflows.

Provides :class:`DecidePrimitive`, which implements
:class:`~beddel.domain.ports.IPrimitive` and enables workflows to record
structured decisions with intent, options, chosen option, and reasoning.

This is an **expansion pack** primitive — it is NOT registered in
:func:`register_builtins`.  Register it explicitly::

    registry.register("decide", DecidePrimitive())
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from beddel.domain.errors import PrimitiveError
from beddel.domain.models import Decision, ExecutionContext
from beddel.domain.ports import IPrimitive
from beddel.error_codes import PRIM_DECIDE_MISSING_CONFIG

__all__ = [
    "DecidePrimitive",
]

logger = logging.getLogger(__name__)

_REQUIRED_KEYS: tuple[str, ...] = ("intent", "chosen", "reasoning")


class DecidePrimitive(IPrimitive):
    """Structured decision capture primitive.

    Creates a :class:`~beddel.domain.models.Decision` record from the step
    config, fires the ``on_decision`` lifecycle hook, persists to the
    configured :class:`~beddel.domain.ports.IDecisionStore` (if available),
    and returns the decision as a dict.

    Config keys:
        intent (str): Required. What the decision is about.
        options (list[str]): Optional. Available options considered.
        chosen (str): Required. The option that was selected.
        reasoning (str): Required. Explanation for the choice.

    Example config::

        {
            "intent": "Select summarization model",
            "options": ["gpt-4o", "claude-3-opus", "gemini-pro"],
            "chosen": "claude-3-opus",
            "reasoning": "Best quality for long documents",
        }
    """

    async def execute(self, config: dict[str, Any], context: ExecutionContext) -> Any:
        """Execute the decide primitive.

        Validates config, creates a :class:`Decision`, fires the
        ``on_decision`` lifecycle hook, persists to the decision store
        (fire-and-forget), and returns the decision as a dict.

        Args:
            config: Primitive configuration containing ``intent``, ``chosen``,
                and ``reasoning`` (required), plus optional ``options``.
            context: Execution context providing runtime data and dependencies.

        Returns:
            A dict representation of the :class:`Decision` (via ``asdict``).

        Raises:
            PrimitiveError: ``BEDDEL-PRIM-400`` if a required config key
                is missing.
        """
        self._validate_config(config, context)

        decision = Decision(
            id=str(uuid4()),
            intent=config["intent"],
            options=config.get("options", []),
            chosen=config["chosen"],
            reasoning=config["reasoning"],
            step_id=context.current_step_id,
            workflow_id=context.workflow_id,
            timestamp=datetime.now(UTC).isoformat(),
        )

        # Fire on_decision lifecycle hook (if available)
        hooks = context.deps.lifecycle_hooks
        if hooks is not None:
            try:
                await hooks.on_decision(decision)
            except Exception:
                logger.warning(
                    "on_decision hook raised (ignored)",
                    exc_info=True,
                )

        # Log to tracer as event — duck typing (no adapter imports)
        tracer = context.deps.tracer
        if tracer is not None and hasattr(tracer, "log_event"):
            try:
                tracer.log_event(
                    name="decision",
                    metadata={
                        "intent": decision.intent,
                        "options": decision.options,
                        "chosen": decision.chosen,
                        "reasoning": decision.reasoning,
                    },
                )
            except Exception:
                logger.warning(
                    "Tracer log_event failed (ignored)",
                    exc_info=True,
                )

        # Persist to decision store — fire-and-forget
        store = context.deps.decision_store
        if store is not None:
            try:
                await store.append(context.workflow_id, decision)
            except Exception:
                logger.warning(
                    "Decision store append failed for workflow %r (ignored)",
                    context.workflow_id,
                    exc_info=True,
                )

        return asdict(decision)

    @staticmethod
    def _validate_config(config: dict[str, Any], context: ExecutionContext) -> None:
        """Validate required config keys.

        Args:
            config: Primitive configuration dict.
            context: Execution context for error details.

        Raises:
            PrimitiveError: ``BEDDEL-PRIM-400`` if a required key is missing.
        """
        for key in _REQUIRED_KEYS:
            if key not in config:
                raise PrimitiveError(
                    code=PRIM_DECIDE_MISSING_CONFIG,
                    message=f"Missing required config key {key!r} for decide primitive",
                    details={
                        "primitive": "decide",
                        "step_id": context.current_step_id,
                        "missing_key": key,
                    },
                )
