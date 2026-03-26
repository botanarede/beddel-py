"""Step filtering utilities for execution strategies.

Provides :class:`StepFilter` — a collection of predicate factories for
filtering workflow steps by primitive type, tags, or composed conditions.
Used by execution strategies (e.g. ``ReflectionStrategy``) to select
step subsets within a workflow.
"""

from __future__ import annotations

from collections.abc import Callable

from beddel.domain.models import Step

StepFilterPredicate = Callable[[Step], bool]
"""Type alias for step filter predicates."""

__all__ = [
    "StepFilter",
    "StepFilterPredicate",
]


class StepFilter:
    """Predicate factories for filtering workflow steps.

    All methods are static — ``StepFilter`` is a namespace, not a stateful
    object.  Predicates are plain callables compatible with Python's
    built-in ``filter()`` function.

    Example::

        from beddel.domain.utils import StepFilter

        llm_filter = StepFilter.filter_by_primitive(["llm", "chat"])
        llm_steps = [s for s in workflow.steps if llm_filter(s)]
    """

    @staticmethod
    def filter_by_primitive(types: list[str]) -> StepFilterPredicate:
        """Return a predicate matching steps whose primitive is in *types*.

        Args:
            types: List of primitive names to match.

        Returns:
            A predicate that returns ``True`` when ``step.primitive``
            is in *types*.
        """
        type_set = set(types)
        return lambda step: step.primitive in type_set

    @staticmethod
    def filter_by_tag(tags: list[str]) -> StepFilterPredicate:
        """Return a predicate matching steps that have any of the given *tags*.

        Args:
            tags: List of tag values to match against ``step.tags``.

        Returns:
            A predicate that returns ``True`` when ``step.tags`` intersects
            with *tags*.
        """
        tag_set = set(tags)
        return lambda step: bool(set(step.tags) & tag_set)

    @staticmethod
    def compose(*predicates: StepFilterPredicate) -> StepFilterPredicate:
        """Return a predicate that is the logical AND of all *predicates*.

        When no predicates are provided, the returned predicate passes all
        steps (``all([])`` is ``True`` in Python).

        Args:
            *predicates: Zero or more step filter predicates.

        Returns:
            A predicate that returns ``True`` only when ALL given
            predicates return ``True``.
        """
        return lambda step: all(p(step) for p in predicates)
