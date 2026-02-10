"""OpenTelemetry tracing adapter — Span management for workflow observability."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from opentelemetry import trace
from opentelemetry.trace import StatusCode

if TYPE_CHECKING:
    from opentelemetry.trace import Span

    from beddel.domain.models import StepDefinition, WorkflowDefinition

logger = logging.getLogger("beddel.adapters.tracing")


class OpenTelemetryAdapter:
    """Adapter implementing ``ITracer`` via the OpenTelemetry API.

    Obtains a tracer from the global ``TracerProvider`` — it does **not**
    create its own provider.  Users are expected to configure their own
    exporter and ``TracerProvider`` before constructing this adapter.

    All span operations are wrapped in ``try/except`` so that tracing
    failures never crash the workflow; errors are logged as warnings.
    """

    def __init__(self) -> None:
        self._tracer = trace.get_tracer("beddel")
        logger.debug("OpenTelemetryAdapter initialised with tracer %r", self._tracer)

    # ------------------------------------------------------------------
    # ITracer protocol methods
    # ------------------------------------------------------------------

    def start_workflow_span(self, workflow: WorkflowDefinition) -> Any:
        """Start a root span for workflow execution.

        Creates a span named ``beddel.workflow.<name>`` with workflow
        metadata attributes.

        Args:
            workflow: The workflow definition being executed.

        Returns:
            An OpenTelemetry ``Span`` handle, or ``INVALID_SPAN`` on failure.
        """
        try:
            name = workflow.metadata.name
            span: Span = self._tracer.start_span(f"beddel.workflow.{name}")
            span.set_attribute("beddel.workflow.name", name)
            span.set_attribute("beddel.workflow.version", workflow.metadata.version)
            span.set_attribute(
                "beddel.workflow.id",
                format(span.get_span_context().trace_id, "032x"),
            )
            logger.debug("start_workflow_span: name=%s", name)
            return span
        except Exception:  # noqa: BLE001
            logger.warning("Failed to start workflow span — tracing disabled for this workflow")
            return trace.INVALID_SPAN

    def start_step_span(self, step: StepDefinition, parent: Any) -> Any:
        """Start a child span for step execution.

        Creates a span named ``beddel.step.<id>`` linked to the *parent*
        workflow span via ``set_span_in_context``.

        Args:
            step: The step definition being executed.
            parent: Parent span handle returned by :meth:`start_workflow_span`.

        Returns:
            An OpenTelemetry ``Span`` handle, or ``INVALID_SPAN`` on failure.
        """
        try:
            ctx = trace.set_span_in_context(parent)
            span: Span = self._tracer.start_span(
                f"beddel.step.{step.id}",
                context=ctx,
            )
            span.set_attribute("beddel.step.id", step.id)
            span.set_attribute("beddel.step.type", step.type)
            logger.debug("start_step_span: id=%s type=%s", step.id, step.type)
            return span
        except Exception:  # noqa: BLE001
            logger.warning("Failed to start step span for step=%s", step.id)
            return trace.INVALID_SPAN

    def end_span(self, span: Any, *, error: str | None = None) -> None:
        """End a span, optionally recording an error.

        Args:
            span: Span handle to end.
            error: If provided, the span is marked as ``ERROR`` with this
                description and an error event is added.
        """
        try:
            if error is not None:
                span.set_status(StatusCode.ERROR, error)
                span.add_event("error", attributes={"error.message": error})
                logger.debug("end_span: error=%s", error)
            else:
                span.set_status(StatusCode.OK)
                logger.debug("end_span: ok")
            span.end()
        except Exception:  # noqa: BLE001
            logger.warning("Failed to end span — tracing data may be incomplete")
