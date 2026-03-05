"""Output-generator primitive — template rendering for Beddel workflows.

Provides :class:`OutputGeneratorPrimitive`, which implements
:class:`~beddel.domain.ports.IPrimitive` and renders templates with variable
interpolation via :class:`~beddel.domain.resolver.VariableResolver`.

Supports three output formats: JSON (with configurable indent), Markdown
(passthrough after resolution), and plain text (default).
"""

from __future__ import annotations

import json
from typing import Any

from beddel.domain.errors import PrimitiveError
from beddel.domain.models import ExecutionContext
from beddel.domain.ports import IPrimitive
from beddel.domain.resolver import VariableResolver

__all__ = [
    "OutputGeneratorPrimitive",
]

_SUPPORTED_FORMATS = frozenset({"json", "markdown", "text"})


class OutputGeneratorPrimitive(IPrimitive):
    """Template rendering primitive with variable interpolation.

    Resolves ``$input``, ``$stepResult``, and ``$env`` references in a
    template string using :class:`VariableResolver`, then formats the
    resolved output based on the ``format`` config key.

    Config keys:
        template (str): Required. Template string containing variable
            references (e.g. ``"Hello, $input.name"``).
        format (str): Optional. Output format — ``"json"``, ``"markdown"``,
            or ``"text"`` (default: ``"text"``).
        indent (int): Optional. JSON indentation level (default: ``2``).
            Only used when ``format`` is ``"json"``.

    Example config::

        {
            "template": "Summary for $input.user: $stepResult.analyze.result",
            "format": "text",
        }
    """

    async def execute(self, config: dict[str, Any], context: ExecutionContext) -> Any:
        """Execute the output-generator primitive.

        Resolves variable references in the template, then formats the
        result according to the configured output format.

        Args:
            config: Primitive configuration containing ``template`` (required)
                and optional ``format`` and ``indent`` keys.
            context: Execution context providing runtime data for variable
                resolution.

        Returns:
            The formatted output string.

        Raises:
            PrimitiveError: ``BEDDEL-PRIM-100`` if ``template`` is missing
                from config.
            PrimitiveError: ``BEDDEL-PRIM-101`` if ``format`` is not one of
                the supported values.
            PrimitiveError: ``BEDDEL-PRIM-102`` if output formatting fails.
        """
        template = self._validate_config(config, context)
        resolved = self._resolve_template(template, context)
        format_type = config.get("format", "text")
        indent = config.get("indent", 2)
        return self._format_output(resolved, format_type, indent=indent)

    @staticmethod
    def _validate_config(config: dict[str, Any], context: ExecutionContext) -> str:
        """Validate required config keys and return the template string.

        Args:
            config: Primitive configuration dict.
            context: Execution context for error details.

        Returns:
            The template string from config.

        Raises:
            PrimitiveError: ``BEDDEL-PRIM-100`` if ``template`` is missing.
            PrimitiveError: ``BEDDEL-PRIM-101`` if ``format`` is unsupported.
        """
        if "template" not in config:
            raise PrimitiveError(
                code="BEDDEL-PRIM-100",
                message="Missing required config key 'template' for output-generator",
                details={
                    "primitive": "output-generator",
                    "step_id": context.current_step_id,
                },
            )

        format_type = config.get("format", "text")
        if format_type not in _SUPPORTED_FORMATS:
            raise PrimitiveError(
                code="BEDDEL-PRIM-101",
                message=(
                    f"Unsupported format '{format_type}' for output-generator. "
                    f"Supported: {', '.join(sorted(_SUPPORTED_FORMATS))}"
                ),
                details={
                    "primitive": "output-generator",
                    "step_id": context.current_step_id,
                    "format": format_type,
                },
            )

        return config["template"]

    @staticmethod
    def _resolve_template(template: str, context: ExecutionContext) -> Any:
        """Resolve variable references in the template string.

        Creates a fresh :class:`VariableResolver` instance and resolves
        ``$input``, ``$stepResult``, and ``$env`` references against the
        execution context.

        Args:
            template: Template string with variable references.
            context: Execution context providing runtime data.

        Returns:
            The resolved value. May be a string, dict, list, or scalar
            depending on the template content and resolved references.
        """
        resolver = VariableResolver()
        return resolver.resolve(template, context)

    @staticmethod
    def _format_output(resolved: Any, format_type: str, *, indent: int = 2) -> str:
        """Apply output formatting to the resolved template value.

        For JSON format, serializes via ``json.dumps``.  For markdown and
        text formats, dict/list values are serialized as JSON (avoiding
        Python repr with single quotes); all other types use ``str()``.

        Args:
            resolved: The resolved template value.
            format_type: One of ``"json"``, ``"markdown"``, or ``"text"``.
            indent: JSON indentation level (only used for ``"json"`` format).

        Returns:
            The formatted output string.

        Raises:
            PrimitiveError: ``BEDDEL-PRIM-102`` if JSON serialization fails.
        """
        if format_type == "json":
            try:
                return json.dumps(resolved, indent=indent, ensure_ascii=False)
            except (TypeError, ValueError, OverflowError) as exc:
                raise PrimitiveError(
                    code="BEDDEL-PRIM-102",
                    message=f"Failed to serialize output as JSON: {exc}",
                    details={
                        "primitive": "output-generator",
                        "format": format_type,
                        "original_error": str(exc),
                    },
                ) from exc

        # Markdown and text: use JSON serialization for dict/list to avoid
        # Python repr (single quotes), plain str() for everything else.
        if isinstance(resolved, (dict, list)):
            return json.dumps(resolved, ensure_ascii=False)
        return str(resolved)
