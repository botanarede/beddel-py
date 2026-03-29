"""Langfuse adapter — observability tracing via the ``ITracer`` port.

This adapter bridges the Beddel domain core to `Langfuse`_, creating
real trace spans with proper attributes for workflow, step, and primitive
execution.  Unlike :class:`~beddel.adapters.otel_adapter.OpenTelemetryAdapter`,
this adapter **never raises** — if the Langfuse server is unavailable or any
SDK call fails, it logs a warning and operates as a no-op.

.. _Langfuse: https://langfuse.com/
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from beddel.domain.ports import ITracer

if TYPE_CHECKING:
    from langfuse.client import (  # type: ignore[import-not-found]
        StatefulTraceClient as LangfuseSpan,
    )
else:
    LangfuseSpan = Any

__all__ = ["LangfuseTracerAdapter"]

_logger = logging.getLogger(__name__)


class LangfuseTracerAdapter(ITracer[LangfuseSpan]):
    """Langfuse tracing adapter implementing :class:`~beddel.domain.ports.ITracer`.

    Provides production-grade observability (traces, spans, cost tracking,
    prompt management) via the Langfuse platform.  Graceful degradation is
    enforced: if the Langfuse server is unreachable or any SDK call fails,
    the adapter logs a warning and silently returns ``None`` — it never
    raises exceptions or blocks workflow execution.

    Args:
        public_key: Langfuse project public key.
        secret_key: Langfuse project secret key.
        host: Langfuse server URL.  Defaults to ``"http://localhost:3000"``
            for self-hosted instances.
        enabled: When ``False``, the adapter behaves as a no-op without
            attempting to connect to Langfuse.

    Example::

        adapter = LangfuseTracerAdapter(
            public_key="pk-lf-...",
            secret_key="sk-lf-...",
            host="https://cloud.langfuse.com",
        )
    """

    def __init__(
        self,
        public_key: str,
        secret_key: str,
        host: str = "http://localhost:3000",
        *,
        enabled: bool = True,
    ) -> None:
        self._enabled = enabled
        self._client: Any = None  # Langfuse | None

        if not enabled:
            return

        try:
            from langfuse import Langfuse

            self._client = Langfuse(
                public_key=public_key,
                secret_key=secret_key,
                host=host,
            )
        except Exception:
            _logger.warning(
                "Failed to initialize Langfuse client — adapter will operate as no-op",
                exc_info=True,
            )

    # Keys handled specially — not forwarded as generic metadata.
    _SPECIAL_KEYS = frozenset({"model", "usage", "prompt_name"})

    def start_span(
        self, name: str, attributes: dict[str, Any] | None = None
    ) -> LangfuseSpan | None:
        """Start a trace span.

        Creates a Langfuse trace with *name* and optional *attributes*.
        Known attribute keys (``model``, ``usage``, ``prompt_name``) are
        mapped to Langfuse-specific fields; all other keys are stored as
        ``metadata``.

        Args:
            name: Human-readable span name (e.g. ``"beddel.workflow"``).
            attributes: Optional key-value attributes to attach to the span.

        Returns:
            An opaque span handle passed back to :meth:`end_span`, or
            ``None`` if the client is unavailable or span creation fails.
        """
        if self._client is None or not self._enabled:
            return None

        try:
            attrs = attributes or {}

            # Separate metadata from special keys.
            metadata: dict[str, Any] = {
                k: v for k, v in attrs.items() if k not in self._SPECIAL_KEYS
            }

            # Build trace kwargs.
            trace_kwargs: dict[str, Any] = {"name": name}

            if "model" in attrs:
                metadata["model"] = attrs["model"]

            if "prompt_name" in attrs:
                metadata["prompt_name"] = attrs["prompt_name"]

            if "usage" in attrs and isinstance(attrs["usage"], dict):
                usage = attrs["usage"]
                trace_kwargs["usage"] = {
                    "input": usage.get("prompt_tokens", 0),
                    "output": usage.get("completion_tokens", 0),
                    "total": usage.get("total_tokens", 0),
                }

            if metadata:
                trace_kwargs["metadata"] = metadata

            return self._client.trace(**trace_kwargs)
        except Exception:
            _logger.warning(
                "Failed to start Langfuse span %r — returning None",
                name,
                exc_info=True,
            )
            return None

    def end_span(
        self, span: LangfuseSpan | None, attributes: dict[str, Any] | None = None
    ) -> None:
        """End a trace span with optional final attributes.

        If *attributes* contains a ``usage`` dict with ``prompt_tokens``,
        ``completion_tokens``, and/or ``total_tokens``, the values are
        forwarded to Langfuse for automatic cost tracking.  Remaining
        attributes are stored as ``metadata``.

        Args:
            span: The opaque span handle returned by :meth:`start_span`,
                or ``None`` if no span was created.
            attributes: Optional key-value attributes to attach before closing.
        """
        if span is None:
            return

        try:
            attrs = attributes or {}
            update_kwargs: dict[str, Any] = {}

            # Extract usage for cost tracking.
            if "usage" in attrs and isinstance(attrs["usage"], dict):
                usage = attrs["usage"]
                update_kwargs["usage"] = {
                    "input": usage.get("prompt_tokens", 0),
                    "output": usage.get("completion_tokens", 0),
                    "total": usage.get("total_tokens", 0),
                }

            # Remaining attributes → metadata.
            metadata: dict[str, Any] = {
                k: v for k, v in attrs.items() if k not in self._SPECIAL_KEYS
            }
            if metadata:
                update_kwargs["metadata"] = metadata

            if update_kwargs:
                span.update(**update_kwargs)

            span.end()
        except Exception:
            _logger.warning(
                "Failed to end Langfuse span — ignoring",
                exc_info=True,
            )

    def flush(self) -> None:
        """Flush buffered spans to the Langfuse backend.

        Sends any pending trace data without tearing down the client.
        Silently ignored if the client is unavailable or disabled.
        """
        if self._client is None or not self._enabled:
            return

        try:
            self._client.flush()
        except Exception:
            _logger.warning(
                "Failed to flush Langfuse client — ignoring",
                exc_info=True,
            )

    def shutdown(self) -> None:
        """Flush pending spans and shut down the Langfuse client.

        Performs a clean teardown: flushes buffered data, then releases
        client resources.  Silently ignored if the client is unavailable
        or disabled.
        """
        if self._client is None or not self._enabled:
            return

        try:
            self.flush()
            self._client.shutdown()
        except Exception:
            _logger.warning(
                "Failed to shut down Langfuse client — ignoring",
                exc_info=True,
            )
