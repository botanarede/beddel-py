"""OpenTelemetry adapter — observability tracing via the ``ITracer`` port.

This adapter bridges the Beddel domain core to `OpenTelemetry`_, creating
real trace spans with proper attributes for workflow, step, and primitive
execution.  Tracing failures are silently ignored to ensure they never
break workflow execution.

.. _OpenTelemetry: https://opentelemetry.io/
"""

from __future__ import annotations

import logging
from typing import Any

from opentelemetry import trace
from opentelemetry.trace import Span as OTelSpan

from beddel import __version__
from beddel.domain.ports import ITracer
from beddel.domain.tracing_utils import extract_token_usage

__all__ = ["OpenTelemetryAdapter"]

_logger = logging.getLogger(__name__)


class OpenTelemetryAdapter(ITracer[OTelSpan]):
    """OpenTelemetry tracing adapter implementing :class:`~beddel.domain.ports.ITracer`.

    Creates real OpenTelemetry spans with attributes for workflow execution,
    step execution, and primitive invocation.  Token usage is tracked via
    the :meth:`_extract_token_attributes` helper.

    Args:
        service_name: The tracer name passed to the provider.  Defaults
            to ``"beddel"``.
        tracer_provider: An optional ``TracerProvider`` instance.  When
            ``None``, falls back to ``trace.get_tracer_provider()``.

    Example::

        from opentelemetry.sdk.trace import TracerProvider
        adapter = OpenTelemetryAdapter(tracer_provider=TracerProvider())
    """

    def __init__(
        self,
        service_name: str = "beddel",
        tracer_provider: trace.TracerProvider | None = None,
    ) -> None:
        provider = tracer_provider or trace.get_tracer_provider()
        self._tracer = provider.get_tracer(service_name, __version__)

    def start_span(self, name: str, attributes: dict[str, Any] | None = None) -> OTelSpan | None:
        """Start a trace span.

        Args:
            name: Human-readable span name (e.g. ``"beddel.workflow"``).
            attributes: Optional key-value attributes to attach to the span.

        Returns:
            An opaque span handle passed back to :meth:`end_span`, or
            ``None`` if span creation fails.
        """
        # Silent-fail by design: tracing must never break workflow execution.
        # Consistent with executor._dispatch_hook pattern for lifecycle hooks.
        # A fail_silent flag was considered (architect rec 4) but deferred —
        # the project convention is that all observability is best-effort.
        try:
            span = self._tracer.start_span(name)
            if attributes:
                for key, value in attributes.items():
                    span.set_attribute(key, value)
            return span  # noqa: TRY300
        except Exception:
            _logger.warning("Failed to start span %r", name, exc_info=True)
            return None

    def end_span(self, span: OTelSpan | None, attributes: dict[str, Any] | None = None) -> None:
        """End a trace span with optional final attributes.

        Args:
            span: The opaque span handle returned by :meth:`start_span`.
            attributes: Optional key-value attributes to attach before closing
                (e.g. token usage).
        """
        if span is None:
            return
        try:
            if attributes:
                for key, value in attributes.items():
                    span.set_attribute(key, value)
            span.end()
        except Exception:
            _logger.warning("Failed to end span", exc_info=True)

    @staticmethod
    def _extract_token_attributes(result: dict[str, Any]) -> dict[str, Any]:
        """Extract ``gen_ai.usage.*`` attributes from a step result dict.

        Delegates to :func:`~beddel.domain.tracing_utils.extract_token_usage`
        for the actual extraction logic.

        Args:
            result: A step result dict that may contain a ``usage`` key
                with token count information.

        Returns:
            A dict of ``gen_ai.usage.*`` attributes suitable for passing to
            :meth:`end_span`, or an empty dict if no usage data is found.
        """
        return extract_token_usage(result)
