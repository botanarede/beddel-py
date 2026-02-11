"""Framework-agnostic SSE (Server-Sent Events) streaming adapter.

Provides ``BeddelSSEAdapter`` which encapsulates all SSE protocol logic
without depending on FastAPI or sse-starlette.  The adapter accepts an
``ExecutionResult`` (or an ``AsyncIterator[str]`` directly) and produces
a well-typed async iterator of ``SSEEvent`` dataclass instances.

``SSEEvent.serialize()`` returns the raw SSE wire format string so that
*any* HTTP framework can write events to the response body.

Usage::

    from beddel.integrations.sse import BeddelSSEAdapter, SSEEvent

    adapter = BeddelSSEAdapter()
    async for event in adapter.stream(execution_result):
        response.write(event.serialize())
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator as AsyncIteratorABC
from dataclasses import dataclass
from typing import TYPE_CHECKING

from beddel.domain.models import BeddelError, BeddelEventType

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, AsyncIterator

    from beddel.domain.models import BeddelEvent, ExecutionResult

# ---------------------------------------------------------------------------
# Structured logging
# ---------------------------------------------------------------------------

logger = logging.getLogger("beddel.integrations.sse")

# ---------------------------------------------------------------------------
# SSEEvent dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SSEEvent:
    """A single Server-Sent Event.

    Attributes:
        event: The event type (e.g. ``"chunk"``, ``"done"``, ``"error"``).
        data: The event payload.  For SSE, each ``data:`` line carries one
            logical line of the payload.
        id: Optional last-event ID for client reconnection.
        retry: Optional reconnection time in **milliseconds**.
    """

    event: str
    data: str
    id: str | None = None
    retry: int | None = None

    def serialize(self) -> str:
        """Serialize this event to the SSE wire format.

        Returns a string ready to be written to an HTTP response body.
        The format follows the `W3C Server-Sent Events`_ specification::

            event: chunk
            data: Hello world

        Each event block is terminated by a blank line (``\\n\\n``).
        Optional ``id:`` and ``retry:`` fields are included when set.

        .. _W3C Server-Sent Events:
           https://html.spec.whatwg.org/multipage/server-sent-events.html
        """
        lines: list[str] = []

        if self.id is not None:
            lines.append(f"id: {self.id}")

        if self.retry is not None:
            lines.append(f"retry: {self.retry}")

        lines.append(f"event: {self.event}")
        for data_line in self.data.split("\n"):
            lines.append(f"data: {data_line}")

        # Trailing blank line terminates the event block.
        return "\n".join(lines) + "\n\n"


# ---------------------------------------------------------------------------
# BeddelSSEAdapter
# ---------------------------------------------------------------------------


class BeddelSSEAdapter:
    """Framework-agnostic adapter that converts workflow results into SSE events.

    The adapter is stateless and has **zero** dependencies on FastAPI or
    sse-starlette — it only uses stdlib types and beddel domain models.

    Typical usage::

        adapter = BeddelSSEAdapter()

        # From an ExecutionResult (auto-detects streaming output):
        async for event in adapter.stream(result):
            await response.write(event.serialize().encode())

        # From a raw AsyncIterator[str]:
        async for event in adapter.stream_iterator(chunks):
            await response.write(event.serialize().encode())
    """

    def __init__(self) -> None:
        logger.debug("BeddelSSEAdapter initialised")

    async def stream(self, result: ExecutionResult) -> AsyncIterator[SSEEvent]:
        """Yield ``SSEEvent`` instances from an ``ExecutionResult``.

        If ``result.output`` is an ``AsyncIterator[str]``, each chunk is
        emitted as a ``chunk`` event followed by a ``done`` sentinel.
        Otherwise the full output is serialised as a single ``chunk``
        event.

        Args:
            result: The workflow execution result to stream.

        Yields:
            ``SSEEvent`` instances in protocol order.
        """
        try:
            if isinstance(result.output, AsyncIteratorABC):
                logger.debug("Streaming async iterator output for workflow %s", result.workflow_id)
                async for event in self.stream_iterator(result.output):
                    yield event
            else:
                logger.debug("Serialising non-streaming output for workflow %s", result.workflow_id)
                payload = json.dumps(result.model_dump(mode="json"))
                yield SSEEvent(event="chunk", data=payload)
                yield SSEEvent(event="done", data="[DONE]")
        except Exception as exc:
            logger.exception("Error during stream() for workflow %s", result.workflow_id)
            yield build_error_event(exc)

    async def stream_iterator(self, iterator: AsyncIterator[str]) -> AsyncIterator[SSEEvent]:
        """Yield ``SSEEvent`` instances from a raw async string iterator.

        This is a lower-level entry point for callers that already have an
        ``AsyncIterator[str]`` and do not need ``ExecutionResult`` handling.

        Args:
            iterator: An async iterator of string chunks.

        Yields:
            ``SSEEvent`` instances in protocol order.
        """
        try:
            async for chunk in iterator:
                yield SSEEvent(event="chunk", data=str(chunk))
            yield SSEEvent(event="done", data="[DONE]")
        except Exception as exc:
            logger.exception("Error during stream_iterator()")
            yield build_error_event(exc)

    async def stream_events(
        self, stream: AsyncGenerator[BeddelEvent, None],
    ) -> AsyncIterator[SSEEvent]:
        """Map a stream of ``BeddelEvent`` instances to ``SSEEvent`` instances.

        Each ``BeddelEvent`` is converted to an ``SSEEvent`` where:
        - ``event`` = the lowercase event type value (e.g. ``"workflow_start"``)
        - ``data`` = JSON-serialised ``BeddelEvent.data``

        After the ``WORKFLOW_END`` event, a ``done`` sentinel is yielded.

        Args:
            stream: An async generator of ``BeddelEvent`` instances
                (typically from ``WorkflowExecutor.execute_stream()``).

        Yields:
            ``SSEEvent`` instances in protocol order.
        """
        try:
            async for event in stream:
                yield SSEEvent(
                    event=event.type.value,
                    data=json.dumps(event.data, default=str),
                )
                if event.type == BeddelEventType.WORKFLOW_END:
                    yield SSEEvent(event="done", data="[DONE]")
        except Exception as exc:
            logger.exception("Error during stream_events()")
            yield build_error_event(exc)



# ---------------------------------------------------------------------------
# Error event builder
# ---------------------------------------------------------------------------


def build_error_event(exc: Exception) -> SSEEvent:
    """Map an exception to a structured SSE error event.

    If *exc* is a :class:`~beddel.domain.models.BeddelError`, the error
    ``code``, ``message``, and ``details`` are extracted directly.
    Otherwise a generic ``INTERNAL_ERROR`` payload is produced.

    Args:
        exc: The exception to convert.

    Returns:
        An ``SSEEvent`` with ``event="error"`` and a JSON-encoded payload.
    """
    if isinstance(exc, BeddelError):
        payload = {
            "code": str(exc.code),
            "message": str(exc),
            "details": exc.details,
        }
    else:
        payload = {
            "code": "INTERNAL_ERROR",
            "message": str(exc),
            "details": {},
        }
    return SSEEvent(event="error", data=json.dumps(payload))


__all__ = ["BeddelSSEAdapter", "SSEEvent", "build_error_event"]
