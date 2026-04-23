"""Event mapping from Beddel domain events to AG-UI protocol events.

Translates :class:`~beddel.domain.models.BeddelEvent` instances into their
AG-UI protocol equivalents.  Unmapped event types return ``None`` so callers
can silently skip them.

AG-UI requires ``TextMessageContentEvent.delta`` to be non-empty — the
mapper enforces this by returning ``None`` when the text chunk is blank.

Example::

    from beddel_ag_ui.mapping import map_event

    agui_event = map_event(
        beddel_event,
        thread_id="t-1",
        run_id="r-1",
        message_id="m-1",
    )
    if agui_event is not None:
        yield agui_event
"""

from __future__ import annotations

from ag_ui.core import (
    BaseEvent,
    EventType as AGUIEventType,
    RunErrorEvent,
    RunFinishedEvent,
    RunStartedEvent,
    StepFinishedEvent,
    StepStartedEvent,
    TextMessageContentEvent,
)

from beddel.domain.models import BeddelEvent, EventType

__all__ = ["map_event"]


def map_event(
    event: BeddelEvent,
    *,
    thread_id: str,
    run_id: str,
    message_id: str,
) -> BaseEvent | None:
    """Map a Beddel domain event to an AG-UI protocol event.

    Args:
        event: The Beddel event to translate.
        thread_id: AG-UI thread identifier for the current run.
        run_id: AG-UI run identifier for the current run.
        message_id: AG-UI message identifier for text content events.

    Returns:
        The corresponding AG-UI event, or ``None`` if the event type has
        no AG-UI equivalent (or if the payload is invalid for AG-UI, e.g.
        an empty text delta).
    """
    et = event.event_type

    if et is EventType.WORKFLOW_START:
        return RunStartedEvent(
            type=AGUIEventType.RUN_STARTED,
            thread_id=thread_id,
            run_id=run_id,
        )

    if et is EventType.STEP_START:
        return StepStartedEvent(
            type=AGUIEventType.STEP_STARTED,
            step_name=event.step_id or "unknown",
        )

    if et is EventType.STEP_END:
        return StepFinishedEvent(
            type=AGUIEventType.STEP_FINISHED,
            step_name=event.step_id or "unknown",
        )

    if et is EventType.TEXT_CHUNK:
        delta = event.data.get("text", "")
        if not delta:
            return None
        return TextMessageContentEvent(
            type=AGUIEventType.TEXT_MESSAGE_CONTENT,
            message_id=message_id,
            delta=delta,
        )

    if et is EventType.WORKFLOW_END:
        return RunFinishedEvent(
            type=AGUIEventType.RUN_FINISHED,
            thread_id=thread_id,
            run_id=run_id,
        )

    if et is EventType.ERROR:
        return RunErrorEvent(
            type=AGUIEventType.RUN_ERROR,
            message=event.data.get("message", "Unknown error"),
            code=event.data.get("code"),
        )

    # Unmapped event type — caller should skip.
    return None
