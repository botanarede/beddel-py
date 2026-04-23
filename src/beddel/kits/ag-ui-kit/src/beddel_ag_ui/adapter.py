"""AG-UI protocol adapter for Beddel workflow events.

Converts :class:`~beddel.domain.models.BeddelEvent` streams into AG-UI
protocol events consumable by CopilotKit and other AG-UI-compatible
frontends.

The adapter manages the ``TextMessage`` lifecycle (start → content → end)
and translates errors into ``RunErrorEvent`` / ``RunFinishedEvent`` pairs
for clean stream termination.

Example usage with a CopilotKit runtime::

    from beddel_ag_ui.adapter import BeddelAGUIAdapter

    async def stream(workflow, context):
        event_stream = executor.execute_stream(workflow, context)
        async for agui_event in BeddelAGUIAdapter.stream_events(event_stream):
            yield agui_event.model_dump_json()
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncGenerator
from typing import final

from ag_ui.core import (
    BaseEvent,
    RunErrorEvent,
    RunFinishedEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    TextMessageStartEvent,
)

from beddel.domain.errors import BeddelError
from beddel.domain.models import BeddelEvent
from beddel.error_codes import INTERNAL_SERVER_ERROR
from beddel_ag_ui.mapping import map_event

__all__ = ["BeddelAGUIAdapter"]

logger = logging.getLogger(__name__)


@final
class BeddelAGUIAdapter:
    """Converts BeddelEvent async streams to AG-UI protocol event streams.

    This is a pure utility class with no instance state. All methods are
    static. Not intended for subclassing (marked ``@final``).

    The yielded events conform to the AG-UI protocol specification and can
    be serialised with ``event.model_dump_json()`` for SSE transport to
    CopilotKit or any AG-UI-compatible frontend.
    """

    @staticmethod
    async def stream_events(
        events: AsyncGenerator[BeddelEvent, None],
        *,
        thread_id: str | None = None,
        run_id: str | None = None,
    ) -> AsyncGenerator[BaseEvent, None]:
        """Convert a BeddelEvent stream to AG-UI protocol events.

        Iterates over the event stream, maps each event via
        :func:`~beddel_ag_ui.mapping.map_event`, and manages the
        ``TextMessage`` lifecycle by emitting ``TextMessageStartEvent``
        before the first content chunk and ``TextMessageEndEvent`` after
        the last.

        If an exception occurs during iteration, emits a
        ``RunErrorEvent`` followed by a ``RunFinishedEvent`` for clean
        stream termination.

        For :class:`~beddel.domain.errors.BeddelError` subclasses the
        error code is taken from ``exc.code``; for all other exceptions
        the ``INTERNAL_SERVER_ERROR`` code from the centralized registry
        is used.

        Args:
            events: Async generator yielding BeddelEvent instances.
            thread_id: AG-UI thread identifier. Generated via
                ``uuid.uuid4().hex`` if not provided.
            run_id: AG-UI run identifier. Generated via
                ``uuid.uuid4().hex`` if not provided.

        Yields:
            AG-UI :class:`~ag_ui.core.BaseEvent` instances suitable for
            serialisation and SSE transport.
        """
        _thread_id = thread_id or uuid.uuid4().hex
        _run_id = run_id or uuid.uuid4().hex
        _message_id = uuid.uuid4().hex
        _text_started = False

        try:
            async for event in events:
                agui_event = map_event(
                    event,
                    thread_id=_thread_id,
                    run_id=_run_id,
                    message_id=_message_id,
                )
                if agui_event is None:
                    continue

                # TextMessage lifecycle: emit start before first content chunk
                if isinstance(agui_event, TextMessageContentEvent) and not _text_started:
                    yield TextMessageStartEvent(
                        message_id=_message_id,
                        role="assistant",
                    )
                    _text_started = True

                yield agui_event

        except BeddelError as exc:
            # Close open text message before error events
            if _text_started:
                yield TextMessageEndEvent(message_id=_message_id)
                _text_started = False

            # Sanitize: strip upstream exception text from adapter errors
            is_adapter_error = exc.code.startswith("BEDDEL-ADAPT")
            safe_message = exc.message.split(":")[0] if is_adapter_error else exc.message
            yield RunErrorEvent(message=safe_message, code=exc.code)
            yield RunFinishedEvent(
                thread_id=_thread_id,
                run_id=_run_id,
            )
        except Exception:
            # Close open text message before error events
            if _text_started:
                yield TextMessageEndEvent(message_id=_message_id)
                _text_started = False

            logger.exception("Unexpected error during AG-UI streaming")
            yield RunErrorEvent(
                message="Internal server error",
                code=INTERNAL_SERVER_ERROR,
            )
            yield RunFinishedEvent(
                thread_id=_thread_id,
                run_id=_run_id,
            )
        else:
            # Normal completion: close open text message
            if _text_started:
                yield TextMessageEndEvent(message_id=_message_id)
