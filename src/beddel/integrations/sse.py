"""SSE (Server-Sent Events) adapter for Beddel workflow events.

Converts :class:`~beddel.domain.models.BeddelEvent` streams into
SSE-compatible dicts consumable by ``sse-starlette``'s
``EventSourceResponse``.

W3C SSE specification compliance: multi-line ``data`` fields are emitted
as separate ``data:`` lines by joining on ``\\ndata: ``.

Example usage with FastAPI + sse-starlette::

    from sse_starlette.sse import EventSourceResponse

    @app.get("/events")
    async def events():
        event_stream = executor.execute_stream(workflow, context)
        sse_stream = BeddelSSEAdapter.stream_events(event_stream)
        return EventSourceResponse(sse_stream)

Each yielded dict has the shape::

    {"event": "text_chunk", "data": '{"event_type":"text_chunk",...}'}
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from typing import final

from beddel.domain.errors import BeddelError
from beddel.domain.models import BeddelEvent
from beddel.error_codes import INTERNAL_SERVER_ERROR

__all__ = ["BeddelSSEAdapter"]


@final
class BeddelSSEAdapter:
    """Converts BeddelEvent async streams to SSE-compatible dict streams.

    This is a pure utility class with no instance state. All methods are
    static. Not intended for subclassing (marked ``@final``).

    The yielded dicts conform to the format expected by ``sse-starlette``'s
    ``EventSourceResponse``:

    - ``event``: The SSE event type string (e.g. ``"text_chunk"``).
    - ``data``: JSON-serialized event payload, with multi-line data joined
      by ``\\ndata: `` per the W3C SSE specification.
    """

    @staticmethod
    async def stream_events(
        events: AsyncGenerator[BeddelEvent, None],
    ) -> AsyncGenerator[dict[str, str], None]:
        """Convert a BeddelEvent stream to SSE-compatible dicts.

        Iterates over the event stream and yields SSE-formatted dicts. If an
        exception occurs during iteration, emits a structured ``error`` event
        followed by a ``done`` event for clean stream termination.

        For :class:`~beddel.domain.errors.BeddelError` subclasses the error
        code is taken from ``exc.code``; for all other exceptions the
        ``INTERNAL_SERVER_ERROR`` code from the centralized registry is used.

        Args:
            events: Async generator yielding BeddelEvent instances.

        Yields:
            Dicts with ``event`` and ``data`` keys suitable for
            ``sse-starlette``'s ``EventSourceResponse``.

        Example::

            async for sse_dict in BeddelSSEAdapter.stream_events(event_stream):
                # sse_dict == {"event": "text_chunk", "data": "{...}"}
                ...
        """
        try:
            async for event in events:
                json_str = event.model_dump_json()
                # W3C SSE: split multi-line JSON and join with \ndata: so
                # sse-starlette emits each line with its own data: prefix.
                lines = json_str.split("\n")
                data = "\ndata: ".join(lines)

                yield {"event": event.event_type.value, "data": data}
        except BeddelError as exc:
            yield {
                "event": "error",
                "data": json.dumps({"code": exc.code, "message": str(exc)}),
            }
            yield {"event": "done", "data": ""}
        except Exception as exc:
            yield {
                "event": "error",
                "data": json.dumps({"code": INTERNAL_SERVER_ERROR, "message": str(exc)}),
            }
            yield {"event": "done", "data": ""}
